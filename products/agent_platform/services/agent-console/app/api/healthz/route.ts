/**
 * `GET /api/healthz` — liveness/readiness signal for the chart's probes
 * and the smoke test in `.github/scripts/smoke-test-agent-console.sh`.
 *
 * Force-static so Next.js doesn't drag the dynamic-route plumbing through
 * what should be a flat 200 — keeps the probe path cheap on every poll.
 */

import { NextResponse } from 'next/server'

export const dynamic = 'force-static'

export function GET(): NextResponse {
    return NextResponse.json({ ok: true })
}
