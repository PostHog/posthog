ALTER TABLE cyclotron_jobs
    ALTER COLUMN vm_state TYPE bytea USING vm_state::bytea,
    ALTER COLUMN metadata TYPE bytea USING metadata::bytea,
    ALTER COLUMN parameters TYPE bytea USING parameters::bytea,
    ADD COLUMN blob bytea;
