# Test cases for warehouse-source-inputs-go-through-store.
# ruff: noqa


class ExternalDataSource:
    job_inputs: dict = {}
    objects = None


class SourceInputsStore:
    pass


source = ExternalDataSource()
queryset = None

# ruleid: warehouse-source-inputs-go-through-store
password = source.job_inputs["password"]

# ruleid: warehouse-source-inputs-go-through-store
schema = (source.job_inputs or {}).get("schema")

# ruleid: warehouse-source-inputs-go-through-store
source.job_inputs = {"host": "db.example.com"}

# ruleid: warehouse-source-inputs-go-through-store
inputs = getattr(source, "job_inputs", None)

# ruleid: warehouse-source-inputs-go-through-store
ExternalDataSource.objects.create(team_id=1, job_inputs={"host": "db.example.com"})

# ruleid: warehouse-source-inputs-go-through-store
new_source = ExternalDataSource(team_id=1, job_inputs={})

# ruleid: warehouse-source-inputs-go-through-store
queryset.update(job_inputs={})

# ok: warehouse-source-inputs-go-through-store
inputs = SourceInputsStore.load(source)

# ok: warehouse-source-inputs-go-through-store
SourceInputsStore.create(inputs={"host": "db.example.com"}, team_id=1)

# ok: warehouse-source-inputs-go-through-store
ExternalDataSource.objects.only("id", "job_inputs").defer("job_inputs")

# ok: warehouse-source-inputs-go-through-store
source.save(update_fields=["job_inputs", "updated_at"])


def run(job_inputs: dict) -> None:
    # ok: warehouse-source-inputs-go-through-store
    parse(job_inputs=job_inputs)


def parse(job_inputs: dict) -> dict:
    return job_inputs
