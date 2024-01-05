INSERT INTO
    job_queue (
        errors,
        metadata,
        last_attempt_finished_at,
        parameters,
        queue,
        status,
        target
    )
VALUES
    -- team:1, plugin_config:2, completed in hour 20
    (
        NULL,
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'webhooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, completed in hour 20 (purposeful duplicate)
    (
        NULL,
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'webhooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, completed in hour 21 (different hour)
    (
        NULL,
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 21:01:18.799371+00',
        '{}',
        'webhooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:3, completed in hour 20 (different plugin_config)
    (
        NULL,
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 3}',
        '2023-12-19 20:01:18.80335+00',
        '{}',
        'webhooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, completed but in a different queue
    (
        NULL,
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'not-webhooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:2, plugin_config:4, completed in hour 20 (different team)
    (
        NULL,
        '{"team_id": 2, "plugin_id": 99, "plugin_config_id": 4}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'webhooks',
        'completed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, failed in hour 20
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'webhooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, failed in hour 20 (purposeful duplicate)
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'webhooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, failed in hour 20 (different error)
    (
        ARRAY ['{"type":"ConnectionError","details":{"error":{"name":"Connection Error"}}}'::jsonb],
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'webhooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, failed in hour 21 (different hour)
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 21:01:18.799371+00',
        '{}',
        'webhooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:3, failed in hour 20 (different plugin_config)
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 3}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'webhooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, failed but in a different queue
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'not-webhooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:2, plugin_config:4, failed in hour 20 (purposeful duplicate)
    (
        ARRAY ['{"type":"TimeoutError","details":{"error":{"name":"Timeout"}}}'::jsonb],
        '{"team_id": 2, "plugin_id": 99, "plugin_config_id": 4}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'webhooks',
        'failed',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, available
    (
        NULL,
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 20:01:18.799371+00',
        '{"body": "hello world", "headers": {}, "method": "POST", "url": "https://myhost/endpoint"}',
        'webhooks',
        'available',
        'https://myhost/endpoint'
    ),
    -- team:1, plugin_config:2, running
    (
        NULL,
        '{"team_id": 1, "plugin_id": 99, "plugin_config_id": 2}',
        '2023-12-19 20:01:18.799371+00',
        '{}',
        'webhooks',
        'running',
        'https://myhost/endpoint'
    );