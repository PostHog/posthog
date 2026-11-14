import { parseJSON } from '~/common/utils/json-parse'

import { durationMs } from '../duration'
import { EXIT_CODE } from '../runner/status'
import { Controller } from './admission'
import { AwsError } from './aws'
import { Manifest, evidenceOf, keyOf } from './lease'
import { CloudProfile, REGION } from './profile'
import { POLL_MS } from './stack'

const REPO = '/opt/posthog'
const SCRIPTS = `${REPO}/nodejs/tests/scenarios/cloud`
const START_TIMEOUT_S = 60
const DELIVERY_TIMEOUT_S = 60
const STOP_TIMEOUT_S = 300
const STOP_WAIT_MS = (STOP_TIMEOUT_S + START_TIMEOUT_S) * 1000
const LIVENESS_MS = 5 * 60_000
const PROBE_WAIT_MS = 2 * START_TIMEOUT_S * 1000
const UNIT_GONE = new Set([3, 4])
const SETTLED = new Set(['Success', 'Failed', 'Cancelled', 'TimedOut'])
const EXIT_CODES = new Set<number>(Object.values(EXIT_CODE))

type Invocation = { Status: string; ResponseCode: number }

const quoted = (value: string): string => `'${value.replace(/'/g, `'\\''`)}'`

const unitOf = (manifest: Manifest): string => `scenario-card-${manifest.runId}`

function hostEnv(profile: CloudProfile, manifest: Manifest): Record<string, string> {
    return {
        SCENARIO_RUN_ID: manifest.runId,
        SCENARIO_EVIDENCE_BUCKET: profile.baseline.evidenceBucket,
        AWS_REGION: REGION,
    }
}

const lastWorkAt = (profile: CloudProfile, manifest: Manifest): number =>
    Date.parse(manifest.expiresAt) - durationMs(profile.admission.teardownAllowance)

async function hostOf({ aws }: Controller, manifest: Manifest): Promise<string | undefined> {
    try {
        const { StackResources } = (await aws.call([
            'cloudformation',
            'describe-stack-resources',
            '--stack-name',
            manifest.stackName,
        ])) as { StackResources: { LogicalResourceId: string; PhysicalResourceId: string }[] }
        return StackResources.find(({ LogicalResourceId }) => LogicalResourceId === 'Host')?.PhysicalResourceId
    } catch (error) {
        if (error instanceof AwsError && error.code === 'ValidationError' && error.stderr.includes('does not exist')) {
            return undefined
        }
        throw error
    }
}

async function settleOnHost(
    controller: Controller,
    instanceId: string,
    commands: string[],
    timeoutSeconds: number,
    until: number,
    signal?: AbortSignal
): Promise<Invocation | undefined> {
    const { aws } = controller
    const { Command } = (await aws.call([
        'ssm',
        'send-command',
        '--instance-ids',
        instanceId,
        '--document-name',
        'AWS-RunShellScript',
        '--timeout-seconds',
        String(DELIVERY_TIMEOUT_S),
        '--parameters',
        JSON.stringify({ commands, executionTimeout: [String(timeoutSeconds)] }),
    ])) as { Command: { CommandId: string } }
    for (;;) {
        await controller.sleep(POLL_MS)
        let invocation: Invocation | undefined
        try {
            invocation = (await aws.call([
                'ssm',
                'get-command-invocation',
                '--command-id',
                Command.CommandId,
                '--instance-id',
                instanceId,
            ])) as Invocation
        } catch (error) {
            if (!(error instanceof AwsError && error.code === 'InvocationDoesNotExist')) {
                throw error
            }
        }
        signal?.throwIfAborted()
        if (invocation && SETTLED.has(invocation.Status)) {
            return invocation
        }
        if (controller.now().getTime() >= until) {
            return undefined
        }
    }
}

async function runOnHost(
    controller: Controller,
    instanceId: string,
    commands: string[],
    timeoutSeconds: number,
    until: number,
    signal?: AbortSignal
): Promise<Invocation> {
    const invocation = await settleOnHost(controller, instanceId, commands, timeoutSeconds, until, signal)
    if (invocation === undefined) {
        throw new Error(`The host command did not finish by ${new Date(until).toISOString()}.`)
    }
    return invocation
}

async function requireHost(controller: Controller, manifest: Manifest): Promise<string> {
    const host = await hostOf(controller, manifest)
    if (host === undefined) {
        throw new Error(`Stack ${manifest.stackName} has no run host.`)
    }
    return host
}

export async function prepareDatabase(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    signal: AbortSignal
): Promise<void> {
    const until = lastWorkAt(profile, manifest)
    const remainingSeconds = Math.floor((until - controller.now().getTime()) / 1000)
    if (remainingSeconds <= 0) {
        throw new Error(`The lease ends at ${manifest.expiresAt}, too soon to seed the backlog.`)
    }
    const host = await requireHost(controller, manifest)
    const env = Object.entries(hostEnv(profile, manifest)).map(([name, value]) => `${name}=${quoted(value)}`)
    const { Status, ResponseCode } = await runOnHost(
        controller,
        host,
        [`cd ${REPO}`, `${env.join(' ')} bash ${SCRIPTS}/host-prepare.sh`],
        remainingSeconds,
        until,
        signal
    )
    if (Status !== 'Success') {
        throw new Error(
            `Migrating and seeding the backlog ended ${Status} (exit ${ResponseCode}). Its log is s3://${profile.baseline.evidenceBucket}/${keyOf(manifest.runId, 'host/prepare.log')}.`
        )
    }
}

export async function startCard(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    signal: AbortSignal
): Promise<void> {
    const until = lastWorkAt(profile, manifest)
    if (controller.now().getTime() >= until) {
        throw new Error(`The lease ends at ${manifest.expiresAt}, too soon to start the card.`)
    }
    const host = await requireHost(controller, manifest)
    const env = Object.entries(hostEnv(profile, manifest)).map(([name, value]) => `--setenv=${name}=${quoted(value)}`)
    const { Status, ResponseCode } = await runOnHost(
        controller,
        host,
        [
            [
                'systemd-run',
                `--unit=${quoted(unitOf(manifest))}`,
                '--property=KillMode=mixed',
                `--property=TimeoutStopSec=${STOP_TIMEOUT_S}`,
                `--working-directory=${REPO}`,
                ...env,
                'bash',
                `${SCRIPTS}/host-run-card.sh`,
            ].join(' '),
        ],
        START_TIMEOUT_S,
        until,
        signal
    )
    if (Status !== 'Success') {
        throw new Error(`Starting the card ended ${Status} (exit ${ResponseCode}).`)
    }
}

async function reportOf(controller: Controller, profile: CloudProfile, manifest: Manifest): Promise<number> {
    const bucket = profile.baseline.evidenceBucket
    const { exitCode, uploaded } = parseJSON(
        await evidenceOf(controller.aws, bucket).get(keyOf(manifest.runId, 'host/done'))
    ) as { exitCode?: unknown; uploaded?: unknown }
    if (typeof exitCode !== 'number' || !EXIT_CODES.has(exitCode)) {
        throw new Error(`The card reported done without a runner exit code: ${JSON.stringify(exitCode)}.`)
    }
    if (uploaded !== true) {
        throw new Error(
            `The card ended with exit ${exitCode} but did not upload its evidence to s3://${bucket}/${keyOf(manifest.runId, 'evidence/')}.`
        )
    }
    return exitCode
}

export async function awaitCard(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    signal: AbortSignal
): Promise<number> {
    const evidence = evidenceOf(controller.aws, profile.baseline.evidenceBucket)
    const done = keyOf(manifest.runId, 'host/done')
    const reported = async (): Promise<boolean> => (await evidence.keys(keyOf(manifest.runId, 'host/'))).includes(done)
    const until = lastWorkAt(profile, manifest)
    let checkedAt = controller.now().getTime()
    for (;;) {
        const isDone = await reported()
        signal.throwIfAborted()
        if (isDone) {
            return await reportOf(controller, profile, manifest)
        }
        const now = controller.now().getTime()
        if (now >= until) {
            throw new Error(`The card did not finish by ${new Date(until).toISOString()}.`)
        }
        if (now - checkedAt >= LIVENESS_MS) {
            checkedAt = now
            const host = await requireHost(controller, manifest)
            const unit = unitOf(manifest)
            const probe = await settleOnHost(
                controller,
                host,
                [`systemctl is-active --quiet ${quoted(unit)}`],
                START_TIMEOUT_S,
                Math.min(until, controller.now().getTime() + PROBE_WAIT_MS),
                signal
            )
            if (probe?.Status === 'Failed' && UNIT_GONE.has(probe.ResponseCode)) {
                if (await reported()) {
                    return await reportOf(controller, profile, manifest)
                }
                throw new Error(`The card's unit ${unit} stopped without reporting done.`)
            }
        }
        await controller.sleep(POLL_MS)
    }
}

export async function stopCard(controller: Controller, profile: CloudProfile, manifest: Manifest): Promise<void> {
    const evidence = evidenceOf(controller.aws, profile.baseline.evidenceBucket)
    const started = keyOf(manifest.runId, 'host/started')
    const done = keyOf(manifest.runId, 'host/done')
    const markers = await evidence.keys(keyOf(manifest.runId, 'host/'))
    if (!markers.includes(started) || markers.includes(done)) {
        return
    }
    const host = await hostOf(controller, manifest)
    if (host === undefined) {
        return
    }
    const { Status, ResponseCode } = await runOnHost(
        controller,
        host,
        [`systemctl stop ${quoted(unitOf(manifest))}`],
        STOP_TIMEOUT_S + START_TIMEOUT_S,
        controller.now().getTime() + STOP_WAIT_MS
    )
    if (!(await evidence.keys(keyOf(manifest.runId, 'host/'))).includes(done)) {
        throw new Error(`the card did not report done after its stop ended ${Status} (exit ${ResponseCode})`)
    }
}
