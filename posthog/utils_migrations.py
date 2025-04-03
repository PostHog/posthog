from django.db import migrations, models
import django.db.models.deletion
import hashlib


def generate_index_id(model_name, field_name, suffix=None):
    """
    Generate a consistent ID for index and constraint names.

    Args:
        model_name: The name of the model
        field_name: The name of the field
        suffix: Optional suffix to differentiate between constraint and index

    Returns:
        A 10-character string to use as an index ID
    """
    # Create a base string to hash - only using model_name ensures same model gets same hash
    base = f"{model_name}_{field_name}"
    if suffix:
        base = f"{base}_{suffix}"

    # Create a hash and take the first 10 characters
    hash_obj = hashlib.md5(base.encode())
    return hash_obj.hexdigest()[:10]


def add_project_field_to_model(model_name):
    """
    Creates a SeparateDatabaseAndState operation to add a project_id field to a model.

    This function handles both the state and database operations, including:
    1. Adding the project ForeignKey field in Django's state
    2. Adding the project_id column to the database
    3. Creating a concurrent index on the project_id field

    Args:
        model_name: The name of the model to add the project field to

    Returns:
        A SeparateDatabaseAndState migration operation
    """
    # Generate consistent IDs for the constraint and index
    # Using only the model_name and field_name with a consistent suffix ensures the same model always gets the same hash
    constraint_id = generate_index_id(model_name, "project_id", "c")
    index_id = generate_index_id(model_name, "project_id", "i")

    table_name = f"posthog_{model_name.lower()}"

    return migrations.SeparateDatabaseAndState(
        state_operations=[
            migrations.AddField(
                model_name=model_name,
                name="project",
                field=models.ForeignKey(
                    null=True, blank=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.project"
                ),
            ),
        ],
        database_operations=[
            migrations.RunSQL(
                f"""
                ALTER TABLE "{table_name}" ADD COLUMN "project_id" bigint NULL
                CONSTRAINT "{table_name}_project_id_{constraint_id}_fk_p"s
                REFERENCES "posthog_project"("id") DEFERRABLE INITIALLY DEFERRED;
                SET CONSTRAINTS "{table_name}_project_id_{constraint_id}_fk_p" IMMEDIATE;""",
                reverse_sql=f"""
                    ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS "project_id";""",
            ),
            # Add index CONCURRENTLY to avoid table locks
            migrations.RunSQL(
                f"""
                CREATE INDEX CONCURRENTLY "{table_name}_project_id_{constraint_id}_{index_id}"
                ON "{table_name}" ("project_id");""",
                reverse_sql=f"""
                    DROP INDEX IF EXISTS "{table_name}_project_id_{constraint_id}_{index_id}";""",
            ),
        ],
    )
