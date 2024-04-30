import asyncpg
import dlt
from typing import Any, Optional
from dlt.common.schema.typing import TColumnSchema
import dataclasses
import psycopg2


@dataclasses.dataclass
class DatabaseCredentials:
    host: str
    port: int
    user: str
    password: str
    database: str
    sslmode: str

    @property
    def dsn(self):
        return (
            f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?sslmode={self.sslmode}"
        )


"""Convert an asyncpg type to a dlt column schema type.
This maps asyncpg types to dlt types based on PostgreSQL to Python type mapping
provided by asyncpg and the dlt data types.
"""
type_mapping: dict[str, dict[str, Any]] = {
    "bigint": {"data_type": "bigint", "precision": 64},
    "smallint": {"data_type": "bigint", "precision": 16},
    "integer": {"data_type": "bigint", "precision": 32},
    "numeric": {"data_type": "decimal", "precision": None, "scale": None},
    "text": {"data_type": "text"},
    "varchar": {"data_type": "text", "precision": None},
    "bytea": {"data_type": "binary"},
    "timestamp": {"data_type": "timestamp"},
    "date": {"data_type": "date"},
    "time": {"data_type": "time"},
    "bool": {"data_type": "bool"},
    "json": {"data_type": "complex"},
    "jsonb": {"data_type": "complex"},
    # Additional mappings based on asyncpg documentation
    "bit": {"data_type": "binary", "precision": None},
    "varbit": {"data_type": "binary", "precision": None},
    "cidr": {"data_type": "text"},
    "inet": {"data_type": "text"},
    "macaddr": {"data_type": "text"},
    "uuid": {"data_type": "text", "codec": None},
    # Types without direct dlt mapping, stored as text
    "box": {"data_type": "text"},
    "circle": {"data_type": "text"},
    "line": {"data_type": "text"},
    "lseg": {"data_type": "text"},
    "money": {"data_type": "decimal", "precision": None, "scale": None},
    "path": {"data_type": "text"},
    "point": {"data_type": "text"},
    "polygon": {"data_type": "text"},
    "interval": {"data_type": "bigint", "precision": 64, "codec": None},
    "float": {"data_type": "double"},
    "double precision": {"data_type": "double"},
}


def asyncpg_type_to_dlt_type(
    pg_type: str, precision: Optional[int] = None, scale: Optional[int] = None
) -> Optional[TColumnSchema]:
    dlt_type = type_mapping.get(pg_type, None)

    if dlt_type:
        col_schema: TColumnSchema = {
            "name": pg_type,
            "data_type": dlt_type["data_type"],
        }
        if "precision" in dlt_type:
            col_schema["precision"] = precision if precision is not None else dlt_type["precision"]
        if "scale" in dlt_type:
            col_schema["scale"] = scale if scale is not None else dlt_type["scale"]

        return col_schema

    return None


def generate_columns_from_rows(rows: list, table_name: str, table_schema: str) -> list[TColumnSchema]:
    """
    Generates a list of column schemas from database rows for a given table, taking into account the table schema.
    Args:
        rows: A list of dictionaries, each representing a row from the database.
        table_name: The name of the table for which to generate the column schemas.
        table_schema: The schema of the table for which to generate the column schemas.
    Returns:
        A list of TColumnSchema objects representing the columns of the table.
    """
    columns: list[TColumnSchema] = []
    for row in rows:
        if row["table_name"] == table_name and row["table_schema"] == table_schema:
            column_name = row["column_name"]
            dlt_type = asyncpg_type_to_dlt_type(row["data_type"], row["precision"], row["scale"])

            if dlt_type is not None:
                column_schema: TColumnSchema = {
                    "name": column_name,
                    "data_type": dlt_type.get("data_type", "text"),
                    "precision": dlt_type.get("precision"),
                    "scale": dlt_type.get("scale"),
                    "nullable": row["is_nullable"] == "YES",
                    "primary_key": row["is_primary_key"],
                    "primary_key": row["is_unique"],
                }
                columns.append(column_schema)
    return columns


def get_schema(credentials: DatabaseCredentials, schema: str):
    conn = psycopg2.connect(dsn=credentials.dsn)

    with conn.cursor() as cur:
        query = """
        SELECT
            t.table_schema,
            t.table_name,
            c.column_name,
            c.data_type,
            CASE
                WHEN c.data_type IN ('numeric', 'decimal') THEN c.numeric_precision
                ELSE c.character_maximum_length
            END as precision,
            c.numeric_scale as scale,
            c.is_nullable,
            c.column_default,
            tc.constraint_type,
            CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN TRUE ELSE FALSE END AS is_primary_key,
            CASE WHEN tc.constraint_type = 'UNIQUE' THEN TRUE ELSE FALSE END AS is_unique
        FROM information_schema.tables t
        INNER JOIN information_schema.columns c ON t.table_name = c.table_name AND t.table_schema = c.table_schema
        LEFT JOIN information_schema.constraint_column_usage ccu ON c.table_name = ccu.table_name AND c.column_name = ccu.column_name
        LEFT JOIN information_schema.table_constraints tc ON ccu.constraint_name = tc.constraint_name
        WHERE t.table_schema = %s
        """
        cur.execute(query, (schema,))
        rows = cur.fetchall()

    # format rows
    rows = [
        {
            "table_schema": row[0],
            "table_name": row[1],
            "column_name": row[2],
            "data_type": row[3],
            "precision": row[4],
            "scale": row[5],
            "is_nullable": row[6],
            "column_default": row[7],
            "constraint_type": row[8],
            "is_primary_key": row[9],
            "is_unique": row[10],
        }
        for row in rows
    ]

    return rows


async def get_table_data(
    credentials: DatabaseCredentials,
    table_name: str,
    table_schema: str,
    chunk_size: int,
    incremental: Optional[dlt.sources.incremental[Any]] = None,
):
    conn = await asyncpg.connect(dsn=credentials.dsn)

    # Register custom type codecs based on the type_mapping
    for pg_type, info in type_mapping.items():
        codec = info.get("codec")
        if codec:
            await conn.set_type_codec(
                pg_type,
                encoder=codec.get("encoder", lambda x: x),
                decoder=codec.get("decoder", lambda x: x),
                format=codec.get("format", "text"),
                schema=codec.get("schema", "pg_catalog"),
            )

    base_query = f"SELECT * FROM {table_schema}.{table_name}"
    query_params: list[Any] = []

    if incremental:
        cursor_column = incremental.cursor_path
        last_value = incremental.last_value
        last_value_func = incremental.last_value_func

        if last_value_func is max:
            order_by = "ASC"
            filter_op = ">="
        elif last_value_func is min:
            order_by = "DESC"
            filter_op = "<="
        else:
            # For custom last_value_func, default behavior without filtering
            order_by = "ASC"
            filter_op = ""

        if last_value is not None and filter_op:
            base_query += f" WHERE {cursor_column} {filter_op} $1 ORDER BY {cursor_column} {order_by}"
            query_params.append(last_value)

    async with conn.transaction():
        # Create a cursor for the query
        cur = await conn.cursor(base_query)
        while True:
            # Fetch a chunk of records from the cursor
            records = await cur.fetch(chunk_size)
            if not records:
                break  # Exit the loop if no more records are available
            yield [dict(record) for record in records]

    await conn.close()


@dlt.source(max_table_nesting=0)
def asyncpg_source(credentials: DatabaseCredentials, schema: str, table_names: list[str], chunk_size: int = 5000):
    schema_rows = get_schema(credentials, schema)

    tables = {}  # Specify key and value types for the Dict
    for table_name, table_schema in {(row["table_name"], row["table_schema"]) for row in schema_rows}:
        if table_name not in table_names:
            continue

        # Generate columns for each table
        columns = generate_columns_from_rows(schema_rows, table_name, table_schema)
        # Create a dlt.resource for each table and store it in the tables dict
        tables[table_name] = dlt.resource(name=table_name, columns=columns)(
            lambda table_name=table_name, table_schema=table_schema, chunk_size=chunk_size: get_table_data(
                credentials, table_name, table_schema, chunk_size
            )
        )

    yield from tables.values()
