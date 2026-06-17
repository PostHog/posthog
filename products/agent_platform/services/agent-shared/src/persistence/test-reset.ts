/**
 * Test-harness schema helper for the v2 agent platform.
 *
 * The schema is owned by Django (the `agent_platform` product DB). This module
 * does NOT define or migrate schema — it carries a generated snapshot of the
 * Django migration so the node test harness can stand up an equivalent local
 * test DB and reset it between cases. There is no production migrate path here
 * anymore (prod runs `migrate_product_databases` via the posthog-django job).
 *
 * Regenerate SCHEMA_SQL after any agent_platform migration change:
 *   DEBUG=1 python manage.py sqlmigrate --database agent_platform_db_writer \
 *     agent_platform 0001
 */

// `pg` is CommonJS; the named-import form breaks at boot under `tsx watch`
// ("does not provide an export named 'Pool'"). Destructure off the default
// import at runtime — same workaround as create-pool.ts.
import pg from 'pg'
const { Pool } = pg

export interface ResetOpts {
    databaseUrl?: string
}

// Truncated in FK-safe order (CASCADE handles the rest).
const AGENT_TABLES = [
    'agent_tool_approval_request',
    'agent_session_credential',
    'agent_sandbox_instance',
    'agent_user',
    'agent_session',
    'agent_revision',
    'agent_application',
]

// Generated from the Django migration — the single source of truth. See header.
const SCHEMA_SQL = `
CREATE TABLE "agent_application" ("id" uuid NOT NULL PRIMARY KEY, "team_id" bigint NOT NULL, "name" varchar(255) NOT NULL, "slug" varchar(63) NOT NULL, "description" text DEFAULT '' NOT NULL, "encrypted_env" text NULL, "archived" boolean DEFAULT false NOT NULL, "archived_at" timestamp with time zone NULL, "created_by_id" bigint NULL, "created_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL, "updated_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL);
CREATE TABLE "agent_revision" ("id" uuid NOT NULL PRIMARY KEY, "team_id" bigint NULL, "state" varchar(16) DEFAULT 'draft' NOT NULL, "bundle_uri" text NOT NULL, "bundle_sha256" varchar(64) NULL, "spec" jsonb NOT NULL, "created_by_id" bigint NULL, "created_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL, "updated_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL, "application_id" uuid NOT NULL, "parent_revision_id" uuid NULL);
ALTER TABLE "agent_application" ADD COLUMN "live_revision_id" uuid NULL CONSTRAINT "agent_application_live_revision_id_96cfb1e8_fk_agent_rev" REFERENCES "agent_revision"("id") DEFERRABLE INITIALLY DEFERRED; SET CONSTRAINTS "agent_application_live_revision_id_96cfb1e8_fk_agent_rev" IMMEDIATE;
CREATE TABLE "agent_sandbox_instance" ("id" uuid NOT NULL PRIMARY KEY, "team_id" bigint NOT NULL, "application_id" uuid NOT NULL, "revision_id" uuid NOT NULL, "session_id" uuid NULL, "provider_kind" text NOT NULL, "provider_sandbox_id" text DEFAULT '' NOT NULL, "state" text DEFAULT 'provisioning' NOT NULL, "error_message" text DEFAULT '' NOT NULL, "created_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL, "last_used_at" timestamp with time zone NULL, "terminated_at" timestamp with time zone NULL);
CREATE TABLE "agent_session" ("id" uuid NOT NULL PRIMARY KEY, "team_id" bigint NOT NULL, "application_id" uuid NOT NULL, "revision_id" uuid NOT NULL, "external_key" text NULL, "idempotency_key" text NULL, "trigger_metadata" jsonb NULL, "state" text DEFAULT 'queued' NOT NULL, "conversation" jsonb DEFAULT '[]' NOT NULL, "pending_inputs" jsonb DEFAULT '[]' NOT NULL, "principal" jsonb NULL, "acl" jsonb DEFAULT '[]' NOT NULL, "pending_elevation_requests" jsonb DEFAULT '[]' NOT NULL, "claimed_at" timestamp with time zone NULL, "retry_count" integer DEFAULT 0 NOT NULL, "usage_total" jsonb DEFAULT '{"tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cache_write": 0, "cost_input": 0, "cost_output": 0, "cost_cache_read": 0, "cost_cache_write": 0, "cost_total": 0}' NOT NULL, "wake_at" timestamp with time zone NULL, "slept_at" timestamp with time zone NULL, "slept_total_minutes" integer DEFAULT 0 NOT NULL, "created_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL, "updated_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL);
CREATE TABLE "agent_session_credential" ("team_id" bigint NULL, "session_id" uuid NOT NULL PRIMARY KEY, "encrypted_credentials" text NOT NULL, "expires_at" timestamp with time zone NOT NULL, "created_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL, "updated_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL);
CREATE TABLE "agent_tool_approval_request" ("id" uuid NOT NULL PRIMARY KEY, "team_id" bigint NOT NULL, "session_id" uuid NOT NULL, "application_id" uuid NOT NULL, "revision_id" uuid NOT NULL, "turn" integer NOT NULL, "tool_call_id" text NOT NULL, "tool_name" text NOT NULL, "proposed_args" jsonb NOT NULL, "args_hash" bytea NOT NULL, "assistant_message" jsonb NOT NULL, "approver_scope" jsonb NOT NULL, "state" text NOT NULL, "decision_by" uuid NULL, "decision_at" timestamp with time zone NULL, "decision_reason" text NULL, "decided_args" jsonb NULL, "dispatch_outcome" jsonb NULL, "created_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL, "expires_at" timestamp with time zone NOT NULL, CONSTRAINT "agent_tool_approval_request_state_valid" CHECK ("state" IN ('queued', 'approving', 'dispatched', 'dispatched_failed', 'rejected', 'expired')));
CREATE TABLE "agent_user" ("id" uuid NOT NULL PRIMARY KEY, "team_id" bigint NOT NULL, "application_id" uuid NOT NULL, "principal_kind" text NOT NULL, "principal_id" text NOT NULL, "metadata" jsonb DEFAULT '{}' NOT NULL, "posthog_user_id" integer NULL, "created_at" timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL);
CREATE INDEX "agent_revis_applica_de45c8_idx" ON "agent_revision" ("application_id", "state");
CREATE INDEX "agent_revis_state_b8bd5c_idx" ON "agent_revision" ("state", "created_at");
CREATE INDEX "agent_appli_team_id_8edb60_idx" ON "agent_application" ("team_id", "archived");
CREATE UNIQUE INDEX "agent_application_unique_active_slug" ON "agent_application" ("team_id", "slug") WHERE NOT "archived";
CREATE INDEX "agent_application_team_id_01a7d41d" ON "agent_application" ("team_id");
ALTER TABLE "agent_revision" ADD CONSTRAINT "agent_revision_application_id_c0f0afd7_fk_agent_application_id" FOREIGN KEY ("application_id") REFERENCES "agent_application" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "agent_revision" ADD CONSTRAINT "agent_revision_parent_revision_id_2b043833_fk_agent_revision_id" FOREIGN KEY ("parent_revision_id") REFERENCES "agent_revision" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "agent_revision_team_id_3d7ee0af" ON "agent_revision" ("team_id");
CREATE INDEX "agent_revision_application_id_c0f0afd7" ON "agent_revision" ("application_id");
CREATE INDEX "agent_revision_parent_revision_id_2b043833" ON "agent_revision" ("parent_revision_id");
CREATE INDEX "agent_application_live_revision_id_96cfb1e8" ON "agent_application" ("live_revision_id");
CREATE INDEX "agent_sandbox_instance_team_id_dfe6ca24" ON "agent_sandbox_instance" ("team_id");
CREATE INDEX "asi_state_idx" ON "agent_sandbox_instance" ((COALESCE("last_used_at", "created_at")), "state");
CREATE INDEX "asi_session_idx" ON "agent_sandbox_instance" ("session_id") WHERE "session_id" IS NOT NULL;
CREATE UNIQUE INDEX "agent_session_idempotency_key_unique" ON "agent_session" ("application_id", "idempotency_key") WHERE "idempotency_key" IS NOT NULL;
CREATE INDEX "agent_session_team_id_f4e3849a" ON "agent_session" ("team_id");
CREATE INDEX "agent_sess_created_idx" ON "agent_session" ("state", "created_at");
CREATE INDEX "agent_sess_updated_idx" ON "agent_session" ("state", "updated_at");
CREATE INDEX "agent_sess_extkey_idx" ON "agent_session" ("application_id", "external_key") WHERE "external_key" IS NOT NULL;
CREATE INDEX "agent_sess_wake_idx" ON "agent_session" ("state", "wake_at") WHERE "wake_at" IS NOT NULL;
CREATE INDEX "agent_session_credential_team_id_717879a5" ON "agent_session_credential" ("team_id");
CREATE INDEX "asc_expires_idx" ON "agent_session_credential" ("expires_at");
CREATE UNIQUE INDEX "agent_tool_approval_request_queued_unique" ON "agent_tool_approval_request" ("session_id", "tool_name", "args_hash") WHERE "state" = 'queued';
CREATE INDEX "agent_tool_approval_request_team_id_c5bb5546" ON "agent_tool_approval_request" ("team_id");
CREATE INDEX "atar_expiry_idx" ON "agent_tool_approval_request" ("state", "expires_at");
CREATE INDEX "atar_team_idx" ON "agent_tool_approval_request" ("team_id", "state", "created_at" DESC);
CREATE INDEX "atar_app_idx" ON "agent_tool_approval_request" ("application_id", "state", "created_at" DESC);
CREATE INDEX "atar_session_idx" ON "agent_tool_approval_request" ("session_id", "created_at" DESC);
ALTER TABLE "agent_user" ADD CONSTRAINT "agent_user_unique_natural_key" UNIQUE ("application_id", "principal_kind", "principal_id");
CREATE INDEX "agent_user_team_id_4702652f" ON "agent_user" ("team_id");
`

/**
 * Reset the agent_* tables in the given (test) database. Applies the schema on
 * first use (idempotent), then truncates every table so each test starts clean.
 */
export async function reset(opts: ResetOpts = {}): Promise<void> {
    const databaseUrl = opts.databaseUrl ?? process.env.AGENT_DB_URL
    if (!databaseUrl) {
        throw new Error('agent-migrations.reset: databaseUrl or AGENT_DB_URL is required')
    }
    const pool = new Pool({ connectionString: databaseUrl, max: 1 })
    try {
        const { rows } = await pool.query("SELECT to_regclass('public.agent_session') AS t")
        if (!rows[0]?.t) {
            await pool.query(SCHEMA_SQL)
        }
        await pool.query(`TRUNCATE ${AGENT_TABLES.map((t) => `"${t}"`).join(', ')} RESTART IDENTITY CASCADE`)
    } finally {
        await pool.end()
    }
}
