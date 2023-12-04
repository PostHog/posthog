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
    completed_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    errors jsonb[],
    max_attempts INT NOT NULL DEFAULT 1,
    finished_at TIMESTAMPTZ DEFAULT NULL,
    parameters JSONB,
    queue TEXT NOT NULL DEFAULT 'default'::text,
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status job_status NOT NULL DEFAULT 'available'::job_status,
    target TEXT NOT NULL
);
