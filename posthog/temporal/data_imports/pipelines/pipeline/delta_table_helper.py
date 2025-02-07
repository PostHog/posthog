from collections.abc import Sequence
import gc
from pyspark.sql import SparkSession, DataFrame
from pyspark.conf import SparkConf
from delta import configure_spark_with_delta_pip
from delta.tables import DeltaTable
from typing import Any
import pyarrow as pa
from dlt.common.normalizers.naming.snake_case import NamingConvention
from django.conf import settings
from sentry_sdk import capture_exception
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.pipeline.utils import arrow_to_spark_schema, spark_to_arrow_schema
from posthog.warehouse.models import ExternalDataJob
from posthog.warehouse.s3 import get_s3_client


def _get_credentials():
    if TEST:
        return {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    return {
        "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
        "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
        "region_name": settings.AIRBYTE_BUCKET_REGION,
        "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


def _get_spark_session_singleton() -> SparkSession:
    if hasattr(_get_spark_session_singleton, "_spark"):
        return _get_spark_session_singleton._spark

    credentials = _get_credentials()

    spark_conf = SparkConf()
    spark_conf.set("spark.hadoop.security.authentication", "simple")
    spark_conf.set("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    spark_conf.set("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    spark_conf.set("spark.sql.execution.arrow.pyspark.enabled", "true")

    spark_conf.set("spark.driver.memory", "8g")  # TODO: change this for prod/local/etc - use env var
    spark_conf.set("spark.driver.memoryOverhead", "1g")
    spark_conf.set("spark.executor.memoryOverhead", "1g")
    spark_conf.set("spark.kubernetes.memoryOverheadFactor", "0.1")

    spark_conf.set("spark.memory.fraction", "0.6")
    spark_conf.set("spark.memory.storageFraction", "0.3")
    spark_conf.set("spark.sql.shuffle.partitions", "16")

    spark_conf.set(
        "spark.hadoop.fs.s3a.aws.credentials.provider", "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider"
    )
    spark_conf.set("spark.hadoop.fs.s3a.access.key", credentials["aws_access_key_id"])
    spark_conf.set("spark.hadoop.fs.s3a.secret.key", credentials["aws_secret_access_key"])
    spark_conf.set("spark.hadoop.fs.s3a.endpoint.region", credentials["region_name"])
    spark_conf.set("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")

    if TEST:
        spark_conf.set("spark.hadoop.fs.s3a.endpoint", credentials.get("endpoint_url", "s3.amazonaws.com"))
        spark_conf.set("spark.hadoop.fs.s3a.path.style.access", "true")

    spark_session = configure_spark_with_delta_pip(
        SparkSession.Builder().appName("DeltaTableHelper").master("local[*]").config(conf=spark_conf),
        ["org.apache.hadoop:hadoop-aws:3.3.4", "com.amazonaws:aws-java-sdk-bundle:1.12.262"],
    ).getOrCreate()

    setattr(_get_spark_session_singleton, "_spark", spark_session)  # noqa: B010

    return spark_session


class DeltaTableHelper:
    _resource_name: str
    _job: ExternalDataJob
    _logger: FilteringBoundLogger
    _spark: SparkSession

    def __init__(self, resource_name: str, job: ExternalDataJob, logger: FilteringBoundLogger) -> None:
        self._resource_name = resource_name
        self._job = job
        self._logger = logger
        self._spark = _get_spark_session_singleton()

    def _get_delta_table_uri(self) -> str:
        normalized_resource_name = NamingConvention().normalize_identifier(self._resource_name)
        uri = f"{settings.BUCKET_URL}/{self._job.folder_path()}/{normalized_resource_name}"

        return uri.replace("s3://", "s3a://")

    def _evolve_delta_schema(self, data_frame: DataFrame) -> None:
        delta_table = self.get_delta_table()
        if delta_table is None:
            raise Exception("Deltalake table not found")

        existing_schema = delta_table.toDF().schema
        new_schema = data_frame.schema

        new_fields = [field for field in new_schema.fields if field.name not in existing_schema.fieldNames()]

        if new_fields:
            empty_df = self._spark.createDataFrame([], new_schema)
            empty_df.write.format("delta").mode("append").option("mergeSchema", "true").save(
                self._get_delta_table_uri()
            )

    def get_delta_table(self) -> DeltaTable | None:
        delta_uri = self._get_delta_table_uri()

        try:
            return DeltaTable.forPath(self._spark, delta_uri)
        except Exception as e:
            error_msg = str(e).lower()
            if "not a Delta table" in error_msg or "delta_missing_delta_table" in error_msg:
                return None

            capture_exception(e)
            raise

    def to_arrows_schema(self) -> pa.Schema:
        table = self.get_delta_table()
        if table is None:
            raise Exception("Deltatable not found")

        return spark_to_arrow_schema(table.toDF().schema)

    def reset_table(self):
        table = self.get_delta_table()
        if table is None:
            return

        delta_uri = self._get_delta_table_uri()

        table.delete()

        s3 = get_s3_client()
        s3.delete(delta_uri, recursive=True)

    def write_to_deltalake(
        self, data: pa.Table, is_incremental: bool, chunk_index: int, primary_keys: Sequence[Any] | None
    ) -> DeltaTable:
        table_size_mb = data.nbytes / (1024 * 1024)
        repartitions = int(table_size_mb / 10)

        self._logger.debug(f"PySpark: table_size_mb = {table_size_mb}. repartitions = {repartitions}")

        data_frame = self._spark.createDataFrame(data.to_pandas(), schema=arrow_to_spark_schema(data))
        data_frame = data_frame.repartition(repartitions)

        delta_table = self.get_delta_table()

        if delta_table:
            self._evolve_delta_schema(data_frame)
            delta_table = self.get_delta_table()

        if is_incremental and delta_table is not None:
            if not primary_keys or len(primary_keys) == 0:
                raise Exception("Primary key required for incremental syncs")

            predicate = " AND ".join([f"source.{c} = target.{c}" for c in primary_keys])

            delta_table.alias("target").merge(
                data_frame.alias("source"), predicate
            ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()

        else:
            mode = "append"
            if chunk_index == 0 or delta_table is None:
                mode = "overwrite"

            data_frame.write.format("delta").mode(mode).option("mergeSchema", "true").save(self._get_delta_table_uri())

        # Remove the data frame from memory once its written
        data_frame.unpersist(blocking=True)
        gc.collect()

        delta_table = self.get_delta_table()
        assert delta_table is not None

        return delta_table

    def compact_table(self) -> None:
        table = self.get_delta_table()
        if table is None:
            raise Exception("Deltatable not found")

        self._logger.debug("Compacting table...")
        table.optimize().executeCompaction()

        self._logger.debug("Vacuuming table...")
        table.vacuum(retentionHours=24)

        self._logger.debug("Compacting and vacuuming complete")
