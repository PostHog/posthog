CREATE OR REPLACE FUNCTION create_partitions(TEXT[])
RETURNS VOID AS $$
DECLARE
    partition_date TEXT;
	partition_name TEXT;
    range_begin timestamp;
    range_end timestamp;
    temp_range_begin timestamp;
    temp_range_end timestamp;
	start_of_week TEXT;
	end_of_week TEXT;
    new_table_name TEXT;
    inner_partition_name TEXT;
    row TEXT;
BEGIN 
    new_table_name := 'new_posthog_event';

    EXECUTE ('SET TIME ZONE UTC ');
    EXECUTE format('CREATE TABLE %s (like posthog_event including defaults) partition by list (event)', new_table_name);

    -- Add dummy timestamp column so that constraints can be met between new partitioned table
    EXECUTE('ALTER TABLE posthog_action_events ADD COLUMN timestamp timestamp, ADD COLUMN event varchar(200);');
    EXECUTE('ALTER TABLE posthog_element ADD COLUMN timestamp timestamp, ADD COLUMN event varchar(200)');

    range_begin := (SELECT date_trunc('week', MIN(timestamp)) as range_begin from posthog_event);
    range_end := (SELECT date_trunc('week', CURRENT_TIMESTAMP) as range_end) + interval '1 week';

    IF range_begin < '2020-01-01 00:00:00-00' THEN
        range_begin := '2020-01-01 00:00:00-00';
    END IF;

    -- Create the partitions from the earliest date until now
    EXECUTE('CREATE TABLE posthog_event_partitions_manifest (event varchar(200) NOT NULL);');
    FOREACH row IN ARRAY $1 LOOP
        EXECUTE format('INSERT INTO posthog_event_partitions_manifest (event) VALUES (''%s'')', row);
        partition_name := 'posthog_event_' || row;
        IF NOT EXISTS
            (SELECT 1
            FROM   information_schema.tables 
            WHERE  table_name = partition_name)
            THEN
            RAISE NOTICE 'Partition created: %', partition_name;
            EXECUTE format('CREATE TABLE %I PARTITION OF public.new_posthog_event FOR VALUES IN ($var$%s$var$) partition by range (timestamp)', partition_name, row);
            temp_range_begin := range_begin;
            WHILE temp_range_begin <= range_end
            LOOP
                partition_date := to_char(temp_range_begin,'YYYY_MM_DD');
                inner_partition_name := partition_name || '_' || partition_date;
                start_of_week := to_char((temp_range_begin),'YYYY_MM_DD');
                end_of_week := to_char((temp_range_begin + interval '1 week'),'YYYY_MM_DD');

                IF NOT EXISTS
                (SELECT 1
                    FROM   information_schema.tables 
                    WHERE  table_name = inner_partition_name)
                    THEN
                    RAISE NOTICE 'Partition created: %', inner_partition_name;
                    EXECUTE format('CREATE TABLE "%s" PARTITION OF public."%s" FOR VALUES FROM (''%s'') to (''%s'')', inner_partition_name, partition_name, start_of_week, end_of_week);
                END IF;

                temp_range_begin := temp_range_begin + interval '1 week';
            END LOOP;
            EXECUTE format('CREATE TABLE "%s_default" PARTITION OF public."%s" DEFAULT', partition_name, partition_name);
        END IF;

    END LOOP;

    partition_name := 'posthog_event_' || 'default';
    EXECUTE ('INSERT INTO posthog_event_partitions_manifest (event) VALUES (''default'')');
    IF NOT EXISTS
        (SELECT 1
        FROM   information_schema.tables 
        WHERE  table_name = partition_name)
        THEN
        RAISE NOTICE 'Partition created: %', partition_name;
        EXECUTE format('CREATE TABLE %I PARTITION OF public.new_posthog_event DEFAULT partition by range (timestamp)', partition_name);
        temp_range_begin := range_begin;
        WHILE temp_range_begin <= range_end
        LOOP
            partition_date := to_char(temp_range_begin,'YYYY_MM_DD');
            inner_partition_name := partition_name || '_' || partition_date;
            start_of_week := to_char((temp_range_begin),'YYYY_MM_DD');
            end_of_week := to_char((temp_range_begin + interval '1 week'),'YYYY_MM_DD');

            IF NOT EXISTS
            (SELECT 1
                FROM   information_schema.tables 
                WHERE  table_name = inner_partition_name)
                THEN
                RAISE NOTICE 'Partition created: %', inner_partition_name;
                EXECUTE format('CREATE TABLE "%s" PARTITION OF public."%s" FOR VALUES FROM (''%s'') to (''%s'')', inner_partition_name, partition_name, start_of_week, end_of_week);
            END IF;

            temp_range_begin := temp_range_begin + interval '1 week';
        END LOOP;
        EXECUTE format('CREATE TABLE "%s_default" PARTITION OF public."%s" DEFAULT', partition_name, partition_name);
    END IF;

    -- Move all data from old table into new table
    EXECUTE ('INSERT INTO public.new_posthog_event (id, event, properties, elements, timestamp, team_id, distinct_id, elements_hash)
    SELECT id, event, properties, elements, timestamp, team_id, distinct_id, elements_hash
    FROM public.posthog_event;');

    -- replace old table with new partitioned table
    EXECUTE ('ALTER TABLE posthog_event RENAME TO old_posthog_event');
    EXECUTE ('ALTER TABLE new_posthog_event RENAME TO posthog_event');

    EXECUTE ('ALTER SEQUENCE posthog_event_id_seq OWNED BY posthog_event."id"');
    EXECUTE ('DROP TABLE old_posthog_event CASCADE');

    EXECUTE ('CREATE UNIQUE INDEX posthog_event_pkey ON public.posthog_event USING btree (id, timestamp, event)');
    EXECUTE ('CREATE INDEX posthog_event_team_id_a8b4c6dc ON public.posthog_event USING btree (team_id)');
    EXECUTE ('CREATE INDEX posthog_event_idx_distinct_id ON public.posthog_event USING btree (distinct_id)');
    EXECUTE ('CREATE INDEX posthog_eve_element_48becd_idx ON public.posthog_event USING btree (elements_hash)');
    EXECUTE ('CREATE INDEX posthog_eve_timesta_1f6a8c_idx ON public.posthog_event USING btree ("timestamp", team_id, event)');
    
    EXECUTE ('ALTER TABLE posthog_event ADD CONSTRAINT posthog_event_team_id_a8b4c6dc_fk_posthog_team_id FOREIGN KEY (team_id) REFERENCES posthog_team(id) DEFERRABLE INITIALLY DEFERRED');
    EXECUTE ('ALTER TABLE posthog_action_events ADD CONSTRAINT posthog_action_events_event_id_7077ea70_fk_posthog_event_id FOREIGN KEY (event_id, timestamp, event) REFERENCES posthog_event(id, timestamp, event) DEFERRABLE INITIALLY DEFERRED');
    EXECUTE ('ALTER TABLE posthog_element ADD CONSTRAINT posthog_element_event_id_bb6549a0_fk_posthog_event_id FOREIGN KEY (event_id, timestamp, event) REFERENCES posthog_event(id, timestamp, event) DEFERRABLE INITIALLY DEFERRED');
END
$$
LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_partitions()
RETURNS VOID AS $$
DECLARE
    partition_date TEXT;
	partition_name TEXT;
    event_table_name TEXT;
    event_table_default_name TEXT;
    range_begin timestamp;
    range_end timestamp;
	start_of_week TEXT;
	end_of_week TEXT;
    row RECORD;
BEGIN 
    
    -- If there is no master table then don't create
    IF NOT EXISTS
        (SELECT 1
        FROM   information_schema.tables 
        WHERE  table_name = 'posthog_event') 
    THEN
        RETURN;
    END IF;

    FOR row IN(SELECT * FROM posthog_event_partitions_manifest) LOOP
        event_table_name := 'posthog_event_' || row.event;
        event_table_default_name := 'temp_' || event_table_name || '_default';
        EXECUTE format('CREATE TABLE %s AS TABLE %s_default' , event_table_default_name, event_table_name);
        EXECUTE format('DROP TABLE %s_default CASCADE', event_table_name);

        EXECUTE format('SELECT date_trunc(''week'', MIN(timestamp)) as range_begin from %s' , event_table_default_name) INTO range_begin;
        range_end := (SELECT date_trunc('week', CURRENT_TIMESTAMP) as range_end) + interval '1 week'; -- Always be a week ahead

        IF range_begin IS NULL THEN
             EXECUTE format('SELECT date_trunc(''week'', MAX(timestamp)) as range_begin from %s' , event_table_name) INTO range_begin;
        END IF;

        IF range_begin IS NULL OR range_begin < '2020-01-01 00:00:00-00' THEN
            range_begin := (SELECT date_trunc('week', CURRENT_TIMESTAMP) as range_begin);
        END IF;

        WHILE range_begin <= range_end
        LOOP
            partition_date := to_char(range_begin,'YYYY_MM_DD');
            partition_name := event_table_name || '_' || partition_date;
            start_of_week := to_char((range_begin),'YYYY_MM_DD');
            end_of_week := to_char((range_begin + interval '1 week'),'YYYY_MM_DD');
            IF NOT EXISTS
                (SELECT 1
                FROM   information_schema.tables 
                WHERE  table_name = partition_name) 
            THEN
                RAISE NOTICE 'Partition created: %', partition_name;
                EXECUTE format('CREATE TABLE %I PARTITION OF %s FOR VALUES FROM (''%s'') to (''%s'')', partition_name, event_table_name, start_of_week, end_of_week);
            END IF;

            range_begin := range_begin + interval '1 week';
        END LOOP;

        EXECUTE format('CREATE TABLE %s_default PARTITION OF %s DEFAULT', event_table_name, event_table_name);

        -- Move all data from old default table into new table
        EXECUTE format('INSERT INTO %s (id, event, properties, elements, timestamp, team_id, distinct_id, elements_hash)
        SELECT id, event, properties, elements, timestamp, team_id, distinct_id, elements_hash
        FROM %s;', event_table_name, event_table_default_name);

        EXECUTE format('DROP TABLE %s CASCADE', event_table_default_name);
    END LOOP;

RETURN;
END
$$
LANGUAGE plpgsql;