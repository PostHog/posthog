# Generated by Django 3.1.12 on 2021-10-05 13:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0175_should_update_person_props_function"),
    ]

    operations = [
        migrations.RunSQL("DROP FUNCTION IF EXISTS should_update_person_props;"),
        migrations.RunSQL("DROP TYPE IF EXISTS person_property_updates;"),
        migrations.RunSQL("DROP FUNCTION IF EXISTS update_person_props;"),
        migrations.RunSQL(
            """
        CREATE TYPE person_property_updates AS (
            key text,
            update_op text,
            update jsonb
        );
        """
        ),
        migrations.RunSQL(
            """
            CREATE FUNCTION update_person_props(
                    person_id int,
                    properties jsonb,
                    properties_last_updated_at jsonb,
                    properties_last_operation jsonb,
                    event_timestamp text,
                    updates person_property_updates []
                ) RETURNS jsonb AS $$
            DECLARE 
                result_props jsonb := properties;
                result_props_last_updated_at jsonb := properties_last_updated_at;
                result_props_last_operation jsonb := properties_last_operation;
                update person_property_updates;
            BEGIN 
                FOREACH update IN ARRAY updates LOOP 
                    IF TRUE= 
                        (SELECT NOT property_exists
                            OR stored_timestamp IS NULL
                            OR last_operation IS NULL
                            OR (
                                update.update_op = 'set'
                                AND event_timestamp > stored_timestamp
                            )
                            OR (
                                last_operation = 'set_once'
                                AND event_timestamp < stored_timestamp
                            )
                        FROM (
                                SELECT properties->
                                update.key IS NOT NULL as property_exists,
                                    properties_last_updated_at->>
                                update.key as stored_timestamp,
                                    properties_last_operation->>
                                update.key as last_operation
                            ) as person_props )
                    THEN 
                        result_props := result_props || update.update;
                        result_props_last_updated_at := result_props_last_updated_at || jsonb_build_object(update.key,  event_timestamp);
                        result_props_last_operation := result_props_last_operation || jsonb_build_object(update.key,  update.update_op);
                    END IF;
                END LOOP;
            UPDATE posthog_person
            SET
                properties = result_props,
                properties_last_updated_at=result_props_last_updated_at,
                properties_last_operation=result_props_last_operation
            WHERE id=person_id;
            RETURN result_props;
            END
            $$ LANGUAGE plpgsql;
        """
        ),
    ]
