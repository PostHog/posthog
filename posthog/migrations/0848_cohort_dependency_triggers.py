from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0847_add_cohort_dependency_table"),
    ]

    operations = [
        # Create function to extract cohort dependencies
        migrations.RunSQL(
            """
            -- This function extracts cohort dependencies from the filters and groups JSONB fields
            CREATE OR REPLACE FUNCTION extract_cohort_dependencies(filters_data jsonb, groups_data jsonb)
            RETURNS TABLE(depends_on_id integer)
            LANGUAGE sql AS $$
            WITH vals AS (
                SELECT cohort_ref_id FROM (
                    -- Find cohort references in filters
                    SELECT jsonb_path_query(filters_data, '$.** ? (@.type == "cohort").value') AS cohort_ref_id
                    WHERE filters_data IS NOT NULL
                    UNION ALL
                    -- Find cohort references in groups only if filters is empty
                    SELECT jsonb_path_query(groups_data, '$[*].properties[*] ? (@.type == "cohort").value') AS cohort_ref_id
                    WHERE groups_data IS NOT NULL AND filters_data IS NULL
                ) _
            )
            SELECT DISTINCT (cohort_ref_id::text)::integer AS depends_on_id
            FROM vals
            -- Filter out non-numeric cohort references. Strings are also valid values, but don't work.
            WHERE jsonb_typeof(cohort_ref_id) = 'number';
            $$;
            """,
            reverse_sql="DROP FUNCTION IF EXISTS extract_cohort_dependencies(jsonb, jsonb);",
        ),
        # Create trigger function to update dependencies
        migrations.RunSQL(
            """
            -- This trigger syncs cohort dependencies
            CREATE OR REPLACE FUNCTION update_cohort_dependencies()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                -- Detect and apply changes. We could simply drop and recreate all dependencies,
                -- however, consider cases where properties change but cohort references do not.
                -- In such a case, this will effectively be a no-op.
                IF TG_OP = 'DELETE' THEN
                    DELETE FROM posthog_cohortdependency WHERE cohort_id = OLD.id;
                    RETURN OLD;
                END IF;
                -- Parse out existing cohort references from filters/groups
                WITH new_deps AS (
                    SELECT depends_on_id
                    FROM extract_cohort_dependencies(NEW.filters, NEW.groups)
                ),
                -- Fetch the existing set of dependencies for this cohort
                existing AS (
                    SELECT depends_on_id
                    FROM posthog_cohortdependency
                    WHERE cohort_id = NEW.id
                ),
                -- Identify which existing dependencies are no longer used
                to_delete AS (
                    SELECT e.depends_on_id
                    FROM existing e
                    LEFT JOIN new_deps n USING (depends_on_id)
                    WHERE n.depends_on_id IS NULL
                ),
                -- Remove the (now) unreferenced cohort dependencies
                del AS (
                    -- Deleting here allows us to keep the CTEs in scope when we insert later
                    DELETE FROM posthog_cohortdependency d
                    USING to_delete x
                    WHERE d.cohort_id = NEW.id
                    AND d.depends_on_id = x.depends_on_id
                    RETURNING 1
                ),
                -- Identify which dependencies are new and not yet indexed
                to_insert AS (
                    SELECT n.depends_on_id
                    FROM new_deps n
                    LEFT JOIN existing e USING (depends_on_id)
                    WHERE e.depends_on_id IS NULL
                )
                -- Insert the new dependencies
                INSERT INTO posthog_cohortdependency (cohort_id, depends_on_id, team_id)
                SELECT NEW.id, dep.id, NEW.team_id
                FROM to_insert i
                JOIN posthog_cohort dep
                    ON dep.id = i.depends_on_id
                    AND dep.team_id = NEW.team_id
                    AND dep.deleted = false
                ON CONFLICT (cohort_id, depends_on_id) DO NOTHING;
                RETURN NEW;
            END;
            $$;
            """,
            reverse_sql="DROP FUNCTION IF EXISTS update_cohort_dependencies();",
        ),
        # Create triggers on posthog_cohort table
        migrations.RunSQL(
            """
            CREATE TRIGGER trigger_cohort_dependencies_insert
                AFTER INSERT ON posthog_cohort
                FOR EACH ROW
                WHEN (NEW.filters IS NOT NULL OR NEW.groups IS NOT NULL)
                EXECUTE FUNCTION update_cohort_dependencies();
            CREATE TRIGGER trigger_cohort_dependencies_update
                AFTER UPDATE ON posthog_cohort
                FOR EACH ROW
                WHEN (NEW.filters IS DISTINCT FROM OLD.filters
                      OR NEW.groups IS DISTINCT FROM OLD.groups
                      OR NEW.deleted IS DISTINCT FROM OLD.deleted)
                EXECUTE FUNCTION update_cohort_dependencies();
            CREATE TRIGGER trigger_cohort_dependencies_delete
                AFTER DELETE ON posthog_cohort
                FOR EACH ROW
                EXECUTE FUNCTION update_cohort_dependencies();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS trigger_cohort_dependencies_insert ON posthog_cohort;
            DROP TRIGGER IF EXISTS trigger_cohort_dependencies_update ON posthog_cohort;
            DROP TRIGGER IF EXISTS trigger_cohort_dependencies_delete ON posthog_cohort;
            """,
        ),
        # Populate existing dependencies
        migrations.RunSQL(
            """
            INSERT INTO posthog_cohortdependency (cohort_id, depends_on_id, team_id)
            SELECT DISTINCT
                c.id as cohort_id,
                deps.depends_on_id,
                c.team_id
            FROM posthog_cohort c
            CROSS JOIN LATERAL extract_cohort_dependencies(c.filters, c.groups) as deps(depends_on_id)
            WHERE c.deleted = false
            AND EXISTS (
                SELECT 1 FROM posthog_cohort dep
                WHERE dep.id = deps.depends_on_id
                AND dep.team_id = c.team_id
                AND dep.deleted = false
            )
            ON CONFLICT (cohort_id, depends_on_id) DO NOTHING;
            """,
            reverse_sql="DELETE FROM posthog_cohortdependency;",
        ),
    ]
