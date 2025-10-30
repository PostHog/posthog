# Disable Kubernetes - we're using docker-compose only
allow_k8s_contexts(k8s_context())

VALID_PROFILES = ['minimal', 'core', 'full']
# Default to 'minimal' - matches how devs actually use bin/start --minimal
# Enable additional services via UI as needed for your work
profile = os.getenv('TILT_PROFILE', 'minimal').lower()
if profile not in VALID_PROFILES:
    fail('Unknown TILT_PROFILE "{}". Expected one of {}'.format(profile, ', '.join(VALID_PROFILES)))

# Allow users to enable/disable resources in UI based on profile
# Resources not in the profile's enabled set will start disabled but can be enabled via UI
config.define_string_list('to-run', args=True)

# Always use full docker-compose file
# Profile controls which services auto-start via dc_resource() below
docker_compose(['docker-compose.dev.yml'])

compose_service_names = []
data = read_yaml('docker-compose.dev.yml')
services = data.get('services', {})
for name in services.keys():
    if name not in compose_service_names:
        compose_service_names.append(name)

# Services that are only needed for full development (disabled by default in minimal)
# These match services excluded from docker-compose.dev-minimal.yml
OPTIONAL_INFRA_SERVICES = [
    'flower',           # Celery monitoring UI
    'kafka_ui',         # Kafka monitoring UI
    'maildev',          # Email testing
    'webhook-tester',   # Webhook testing
    'echo_server',      # HTTP echo server for tests
    'livestream',       # Session replay livestream
    'elasticsearch',    # Search and logs
    'temporal',         # Workflow engine
    'temporal-admin-tools',
    'temporal-ui',      # Temporal UI
    'otel-collector',   # OpenTelemetry collector
    'log-capture',      # Log aggregation
    'jaeger',           # Distributed tracing UI
    'localstack',       # AWS services emulation
]

COMMON_IGNORES = [
    '.git',
    '.idea',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '__pycache__',
    '**/__pycache__',
    '.venv',
    'dist',
    'frontend/dist',
    'node_modules',
    'frontend/node_modules',
    'staticfiles',
    'rust/target',
]

# Note: Tilt doesn't have a global ignore() function.
# Ignores are passed per-resource via the 'ignore' parameter in local_resource()
# for pattern in COMMON_IGNORES:
#     ignore(pattern)

repo_root = str(local('pwd', quiet=True)).strip()

def common_env(profile):
    env = {
        'REPOSITORY_ROOT': repo_root,
        'DEBUG': '1',
        'SKIP_SERVICE_VERSION_REQUIREMENTS': '1',
        'BILLING_SERVICE_URL': os.getenv('BILLING_SERVICE_URL', 'https://billing.dev.posthog.dev'),
        'HOG_HOOK_URL': os.getenv('HOG_HOOK_URL', 'http://localhost:3300/hoghook'),
        'API_QUERIES_PER_TEAM': os.getenv('API_QUERIES_PER_TEAM', '{"1": 100}'),
        'DAGSTER_HOME': repo_root + '/.dagster_home',
        'DAGSTER_UI_HOST': os.getenv('DAGSTER_UI_HOST', 'localhost'),
        'DAGSTER_UI_PORT': os.getenv('DAGSTER_UI_PORT', '3030'),
        'DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN': os.getenv('DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN', '3000'),
        'OTEL_SERVICE_NAME': os.getenv('OTEL_SERVICE_NAME', 'posthog-local-dev'),
        'OTEL_PYTHON_LOG_LEVEL': os.getenv('OTEL_PYTHON_LOG_LEVEL', 'debug'),
        'OTEL_EXPORTER_OTLP_ENDPOINT': os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://localhost:4317'),
        'OTEL_TRACES_EXPORTER': os.getenv('OTEL_TRACES_EXPORTER', 'otlp'),
        'OTEL_METRICS_EXPORTER': os.getenv('OTEL_METRICS_EXPORTER', 'none'),
        'OTEL_LOGS_EXPORTER': os.getenv('OTEL_LOGS_EXPORTER', 'none'),
        'OTEL_PYTHON_DJANGO_INSTRUMENT': os.getenv('OTEL_PYTHON_DJANGO_INSTRUMENT', 'true'),
        'OTEL_PYTHON_DJANGO_MIDDLEWARE_POSITION': os.getenv('OTEL_PYTHON_DJANGO_MIDDLEWARE_POSITION', '1'),
    }
    if profile == 'minimal':
        env.update({'OTEL_SDK_DISABLED': 'true'})
    else:
        env.update({
            'OTEL_SDK_DISABLED': os.getenv('OTEL_SDK_DISABLED', 'false'),
            'OTEL_TRACES_SAMPLER': os.getenv('OTEL_TRACES_SAMPLER', 'parentbased_traceidratio'),
            'OTEL_TRACES_SAMPLER_ARG': os.getenv('OTEL_TRACES_SAMPLER_ARG', '1'),
        })
    return env

BASE_ENV = common_env(profile)

PYTHON_DEPS = [
    'manage.py',
    'posthog/',
    'ee/',
    'common/',
    'products/',
    'pyproject.toml',
    'uv.lock',
    'bin/start-backend',
    'bin/start-celery',
]

FRONTEND_DEPS = [
    'frontend/',
    'bin/start-frontend',
    'package.json',
    'pnpm-lock.yaml',
    'pnpm-workspace.yaml',
    'turbo.json',
    'tsconfig.json',
    'tsconfig.dev.json',
]

PLUGIN_SERVER_DEPS = [
    'plugin-server/',
    'bin/plugin-server',
    'package.json',
    'pnpm-lock.yaml',
    'pnpm-workspace.yaml',
    'turbo.json',
    'common/',
    'posthog/',
    'ee/',
]

RUST_DEPS = [
    'rust/',
    'bin/start-rust-service',
    'rust/Cargo.toml',
    'rust/Cargo.lock',
]

MIGRATION_DEPS = PYTHON_DEPS + [
    'bin/check_postgres_up',
    'bin/check_kafka_clickhouse_up',
]

LOCAL_RESOURCE_DEFAULTS = {
    'allow_parallel': True,
}

ALL_PROFILES = set(VALID_PROFILES)

def add_local_resource(name, cmd, deps=None, resource_deps=None, labels=None, extra_env=None, trigger_mode=TRIGGER_MODE_AUTO, auto_init=False, serve_cmd=None, profiles=ALL_PROFILES, ignores=None):
    # Determine if resource should auto-start based on profile
    # Resources always get created (visible in UI), but may start disabled
    should_auto_init = auto_init if profile in profiles else False

    env = dict(BASE_ENV)
    if extra_env:
        for k, v in extra_env.items():
            env[k] = v
    kwargs = {}
    kwargs.update(LOCAL_RESOURCE_DEFAULTS)
    if resource_deps:
        kwargs['resource_deps'] = resource_deps
    if labels:
        kwargs['labels'] = labels
    if serve_cmd:
        kwargs['serve_cmd'] = serve_cmd
    if ignores:
        kwargs['ignore'] = ignores
    local_resource(
        name=name,
        cmd=cmd,
        deps=deps or [],
        env=env,
        trigger_mode=trigger_mode,
        auto_init=should_auto_init,
        **kwargs
    )

# Bootstrap
add_local_resource(
    name='download-mmdb',
    cmd='./bin/download-mmdb',
    deps=['bin/download-mmdb'],
    trigger_mode=TRIGGER_MODE_MANUAL,
    auto_init=True,
    profiles=ALL_PROFILES,
)

# Core application services
add_local_resource(
    name='backend',
    cmd='./bin/start-backend',
    deps=PYTHON_DEPS,
    resource_deps=['db', 'redis', 'kafka', 'clickhouse'],
    labels=['minimal'],
    auto_init=True,
    profiles=set(['minimal', 'core', 'full']),
)

add_local_resource(
    name='celery-worker',
    cmd='./bin/start-celery worker',
    deps=PYTHON_DEPS,
    resource_deps=['db', 'redis', 'kafka', 'clickhouse'],
    labels=['minimal'],
    auto_init=True,
    profiles=set(['minimal', 'core', 'full']),
)

add_local_resource(
    name='celery-beat',
    cmd='./bin/start-celery beat',
    deps=PYTHON_DEPS,
    resource_deps=['db', 'redis', 'kafka', 'clickhouse'],
    labels=['core'],
    auto_init=False,  # Fixed: mprocs-minimal has autostart: false
    profiles=set(['core', 'full']),
)

plugin_cmd = './bin/plugin-server'
plugin_env = {}
if profile == 'minimal':
    plugin_cmd = './bin/plugin-server --no-restart-loop'
    plugin_env['SESSION_RECORDING_V2_METADATA_SWITCHOVER'] = '1970-01-01'
add_local_resource(
    name='plugin-server',
    cmd=plugin_cmd,
    deps=PLUGIN_SERVER_DEPS,
    resource_deps=['db', 'redis', 'kafka', 'clickhouse'],
    extra_env=plugin_env,
    labels=['minimal'],
    auto_init=True,
    profiles=set(['minimal', 'core', 'full']),
)

add_local_resource(
    name='frontend',
    cmd='./bin/start-frontend',
    deps=FRONTEND_DEPS,
    serve_cmd='curl -fsS http://localhost:3000/ >/dev/null || exit 1',
    labels=['minimal'],
    auto_init=True,
    profiles=set(['minimal', 'core', 'full']),
)

# Temporal workers
TEMPORAL_PROFILES = set(['core', 'full'])
add_local_resource(
    name='temporal-worker-general-purpose',
    cmd='python manage.py start_temporal_worker --task-queue general-purpose-task-queue',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['core'],
    profiles=TEMPORAL_PROFILES,
)

add_local_resource(
    name='temporal-worker-batch-exports',
    cmd='python manage.py start_temporal_worker --task-queue batch-exports-task-queue --metrics-port 8002',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['core'],
    profiles=TEMPORAL_PROFILES,
)

add_local_resource(
    name='temporal-worker-data-warehouse',
    cmd='python manage.py start_temporal_worker --task-queue data-warehouse-task-queue --metrics-port 8003',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['core'],
    profiles=TEMPORAL_PROFILES,
)

add_local_resource(
    name='temporal-worker-data-warehouse-compaction',
    cmd='python manage.py start_temporal_worker --task-queue data-warehouse-compaction-task-queue --metrics-port 8004',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['core'],
    profiles=TEMPORAL_PROFILES,
)

add_local_resource(
    name='temporal-worker-data-modeling',
    cmd='python manage.py start_temporal_worker --task-queue data-modeling-task-queue --metrics-port 8005',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['core'],
    profiles=TEMPORAL_PROFILES,
)

add_local_resource(
    name='temporal-worker-tasks-agent',
    cmd='python manage.py start_temporal_worker --task-queue tasks-task-queue --metrics-port 8007',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['core'],
    profiles=TEMPORAL_PROFILES,
)

add_local_resource(
    name='temporal-worker-billing',
    cmd='python manage.py start_temporal_worker --task-queue billing-task-queue --metrics-port 8008',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['core'],
    profiles=TEMPORAL_PROFILES,
)

add_local_resource(
    name='temporal-worker-video-export',
    cmd='python manage.py start_temporal_worker --task-queue video-export-task-queue --metrics-port 8009',
    deps=PYTHON_DEPS + ['bin/check_video_deps'],
    resource_deps=['temporal'],
    labels=['full'],
    profiles=set(['full']),
)

add_local_resource(
    name='temporal-worker-session-replay',
    cmd='python manage.py start_temporal_worker --task-queue session-replay-task-queue --metrics-port 8010',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['full'],
    profiles=set(['full']),
)

add_local_resource(
    name='temporal-worker-analytics-platform',
    cmd='python manage.py start_temporal_worker --task-queue analytics-platform-task-queue --metrics-port 8011',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['full'],
    profiles=set(['full']),
)

add_local_resource(
    name='temporal-worker-weekly-digest',
    cmd='python manage.py start_temporal_worker --task-queue weekly-digest-task-queue --metrics-port 8012 --use-pydantic-converter',
    deps=PYTHON_DEPS,
    resource_deps=['temporal'],
    labels=['full'],
    profiles=set(['full']),
)

add_local_resource(
    name='temporal-worker-max-ai',
    cmd='nodemon -w common -w dags -w ee -w posthog -w products -w pyproject.toml -e py --signal SIGTERM --exec "python manage.py start_temporal_worker --task-queue max-ai-task-queue --metrics-port 8006"',
    deps=PYTHON_DEPS + ['dags/', 'products/', 'pyproject.toml'],
    resource_deps=['temporal'],
    labels=['full'],
    profiles=set(['full']),
)

# Supporting services
add_local_resource(
    name='dagster',
    cmd='dagster dev --workspace $DAGSTER_HOME/workspace.yaml -p $DAGSTER_UI_PORT',
    deps=['dags/', '.dagster_home/workspace.yaml'],
    resource_deps=['db', 'kafka', 'clickhouse'],
    labels=['core'],
    auto_init=True,
    profiles=set(['core', 'full']),
)

# Rust services
add_local_resource(
    name='property-defs-rs',
    cmd='bin/start-rust-service property-defs-rs',
    deps=RUST_DEPS,
    resource_deps=['db', 'kafka'],
    labels=['minimal'],
    auto_init=True,
    profiles=set(['minimal', 'core', 'full']),
)

add_local_resource(
    name='feature-flags-local',
    cmd='bin/start-rust-service feature-flags',
    deps=RUST_DEPS + ['share/'],
    resource_deps=['db', 'redis'],
    labels=['minimal'],
    auto_init=True,
    profiles=set(['minimal', 'core', 'full']),
)

add_local_resource(
    name='capture',
    cmd='bin/start-rust-service capture',
    deps=RUST_DEPS,
    resource_deps=['db', 'kafka'],
    labels=['minimal'],
    auto_init=True,
    profiles=set(['minimal', 'core', 'full']),
)

add_local_resource(
    name='capture-replay',
    cmd='bin/start-rust-service capture-replay',
    deps=RUST_DEPS,
    resource_deps=['db', 'kafka'],
    labels=['core'],
    profiles=set(['core', 'full']),
)

add_local_resource(
    name='plugin-cyclotron-janitor',
    cmd='bin/start-rust-service cyclotron-janitor',
    deps=RUST_DEPS,
    resource_deps=['db', 'kafka'],
    labels=['full'],
    profiles=set(['full']),
)

add_local_resource(
    name='cymbal',
    cmd='bin/start-rust-service cymbal',
    deps=RUST_DEPS,
    resource_deps=['db', 'kafka'],
    labels=['full'],
    auto_init=True,
    profiles=set(['full']),
)

add_local_resource(
    name='embedding-worker',
    cmd='bin/start-rust-service embedding-worker',
    deps=RUST_DEPS,
    resource_deps=['kafka'],
    labels=['core'],
    auto_init=True,
    profiles=set(['core', 'full']),
)

add_local_resource(
    name='batch-import-worker',
    cmd='bin/start-rust-service batch-import-worker',
    deps=RUST_DEPS,
    resource_deps=['db', 'kafka'],
    labels=['full'],
    auto_init=True,
    profiles=set(['full']),
)

# Database setup
add_local_resource(
    name='migrate-postgres',
    cmd='python manage.py migrate',
    deps=MIGRATION_DEPS,
    resource_deps=['db'],
    trigger_mode=TRIGGER_MODE_MANUAL,
    auto_init=True,
    labels=['migrations'],
    profiles=set(['minimal', 'core', 'full']),
)

add_local_resource(
    name='migrate-clickhouse',
    cmd='python manage.py migrate_clickhouse',
    deps=MIGRATION_DEPS,
    resource_deps=['clickhouse', 'kafka'],
    trigger_mode=TRIGGER_MODE_MANUAL,
    auto_init=True,
    labels=['migrations'],
    profiles=set(['minimal', 'core', 'full']),
)

add_local_resource(
    name='migrate-persons-db',
    cmd='cd rust && DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog_persons sqlx migrate run --source persons_migrations',
    deps=['rust/', 'rust/Cargo.toml', 'rust/Cargo.lock', 'rust/persons_migrations/'],
    resource_deps=['db'],
    trigger_mode=TRIGGER_MODE_MANUAL,
    auto_init=True,
    labels=['migrations'],
    profiles=set(['minimal', 'core', 'full']),
)

add_local_resource(
    name='migrate-behavioral-cohorts',
    cmd='rust/bin/migrate-behavioral-cohorts',
    deps=['rust/bin/migrate-behavioral-cohorts', 'rust/Cargo.toml', 'rust/Cargo.lock'],
    resource_deps=['db'],
    trigger_mode=TRIGGER_MODE_MANUAL,
    auto_init=True,
    labels=['migrations'],
    profiles=set(['minimal', 'core', 'full']),
)

generate_demo_deps = PYTHON_DEPS + ['dags/', 'bin/check_dagster_graphql_up']
generate_demo_resource_deps = [
    'db',
    'kafka',
    'dagster',
    'migrate-postgres',
    'migrate-clickhouse',
    'migrate-persons-db',
    'migrate-behavioral-cohorts',
]

add_local_resource(
    name='generate-demo-data',
    cmd='bin/check_dagster_graphql_up && ./manage.py generate_demo_data',
    deps=generate_demo_deps,
    resource_deps=generate_demo_resource_deps,
    trigger_mode=TRIGGER_MODE_MANUAL,
    auto_init=True,
    labels=['fixtures'],
    profiles=set(['core', 'full']),
)

# Optional tooling
add_local_resource(
    name='storybook',
    cmd='pnpm --filter=@posthog/storybook install && pnpm run storybook',
    deps=['frontend/', 'package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml', 'turbo.json'],
    trigger_mode=TRIGGER_MODE_MANUAL,
    profiles=set(['core', 'full']),
)

add_local_resource(
    name='hedgebox-dummy',
    cmd='bin/check_postgres_up && cd hedgebox-dummy && pnpm install && pnpm run dev',
    deps=['hedgebox-dummy/', 'pnpm-lock.yaml', 'pnpm-workspace.yaml'],
    trigger_mode=TRIGGER_MODE_MANUAL,
    profiles=set(['full']),
)

# Configure docker-compose services with labels and auto_init based on profile
#
# New docker-compose services are automatically discovered and loaded:
# - Parsed from docker-compose.dev.yml on every Tilt run
# - Receive fallback ['infra'] label if not explicitly categorized below
# - Auto-start in ALL profiles (including minimal) by default
# - Add service to OPTIONAL_INFRA_SERVICES list if it should be disabled in minimal
#
# Base infra services (minimal)
MINIMAL_INFRA = ['proxy', 'db', 'redis', 'redis7', 'clickhouse', 'zookeeper', 'kafka', 'objectstorage']
# Core infra additions
CORE_INFRA = ['temporal', 'temporal-admin-tools', 'temporal-ui']
# Monitoring/dev tools (full)
MONITORING_SERVICES = ['flower', 'kafka_ui', 'maildev', 'webhook-tester', 'echo_server', 'jaeger']
# Full infra additions
FULL_INFRA = ['livestream', 'elasticsearch', 'otel-collector', 'log-capture', 'localstack']

for svc in compose_service_names:
    # Skip services that have local versions to avoid conflicts
    if svc in ['feature-flags', 'capture']:
        continue

    # Determine labels based on service type
    if svc in MINIMAL_INFRA:
        labels = ['minimal']
    elif svc in CORE_INFRA:
        labels = ['core']
    elif svc in MONITORING_SERVICES:
        labels = ['full']
    elif svc in FULL_INFRA:
        labels = ['full']
    else:
        labels = ['minimal']  # Fallback for any unclassified services (auto-start by default)

    # Optional services don't auto-start in minimal profile but are still visible in UI
    should_auto_init = profile != 'minimal' or svc not in OPTIONAL_INFRA_SERVICES
    dc_resource(svc, labels=labels, auto_init=should_auto_init)

# Disable docker-compose versions in favor of local rust services
# Only disable if they exist in the compose file
if 'feature-flags' in compose_service_names:
    dc_resource('feature-flags', labels=['disabled'])
if 'capture' in compose_service_names:
    dc_resource('capture', labels=['disabled'])

print('Tilt profile: {} (enabled services auto-started, toggle groups in UI as needed)'.format(profile))
