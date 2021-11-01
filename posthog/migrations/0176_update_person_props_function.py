# Generated by Django 3.1.12 on 2021-10-05 13:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0175_should_update_person_props_function"),
    ]

    operations = [
        migrations.RunSQL("DROP FUNCTION IF EXISTS should_update_person_props;", ""),
        migrations.RunSQL("DROP TYPE IF EXISTS person_property_update;", ""),
        migrations.RunSQL("DROP FUNCTION IF EXISTS update_person_props;", ""),
        migrations.RunSQL(
            """
        CREATE TYPE person_property_update AS (
            update_op text,
            key text,
            value jsonb
        );
        """,
            "DROP TYPE IF EXISTS person_property_update",
        ),
        migrations.RunSQL(
            """
            -- not-null-ignore
            CREATE FUNCTION update_person_props(
                    person_id int,
                    event_timestamp text,
                    property_updates person_property_update []
                ) RETURNS void AS $$
            DECLARE 
                props jsonb;
                props_last_updated_at jsonb;
                props_last_operation jsonb;
                property_update person_property_update;
            BEGIN 
                SELECT properties, COALESCE(properties_last_updated_at, '{}'::jsonb), COALESCE(properties_last_operation, '{}'::jsonb) 
                INTO props, props_last_updated_at, props_last_operation 
                FROM posthog_person WHERE id=person_id
                FOR UPDATE; -- acquire a row-level lock here
                FOREACH property_update IN ARRAY property_updates LOOP 
                    IF TRUE= 
                        (SELECT NOT property_exists
                            OR (
                                property_update.update_op = 'set' AND 
                                (
                                    stored_timestamp IS NULL OR
                                    last_operation IS NULL OR
                                    event_timestamp > stored_timestamp OR
                                    (event_timestamp=stored_timestamp AND last_operation = 'set_once')
                                )
                            )
                            OR (
                                last_operation = 'set_once'
                                AND event_timestamp < COALESCE(stored_timestamp, '0')
                            )
                        FROM (
                                SELECT 
                                props->property_update.key IS NOT NULL as property_exists,
                                props_last_updated_at->>property_update.key as stored_timestamp,
                                props_last_operation->>property_update.key as last_operation
                            ) as person_props )
                    THEN 
                        props := props || jsonb_build_object(property_update.key,  property_update.value);
                        props_last_updated_at := props_last_updated_at || jsonb_build_object(property_update.key,  event_timestamp);
                        props_last_operation := props_last_operation || jsonb_build_object(property_update.key,  property_update.update_op);
                    END IF;
                END LOOP;
            UPDATE posthog_person
            SET
                properties = props,
                properties_last_updated_at=props_last_updated_at,
                properties_last_operation=props_last_operation
            WHERE id=person_id;
            END
            $$ LANGUAGE plpgsql;
        """,
            "DROP FUNCTION IF EXISTS update_person_props",
        ),
    ]
