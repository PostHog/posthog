CREATE TYPE job_status AS ENUM(
    'available',
    'completed',
    'failed',
    'running'
);

CREATE TABLE job_queue(
    id BIGSERIAL PRIMARY KEY,
    attempt INT NOT NULL DEFAULT 0,
    attempted_at TIMESTAMPTZ DEFAULT NULL,
    attempted_by TEXT[] DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ DEFAULT NULL,
    started_at TIMESTAMPTZ DEFAULT NULL,
    status job_status NOT NULL DEFAULT 'available'::job_status,
    parameters JSONB
);
