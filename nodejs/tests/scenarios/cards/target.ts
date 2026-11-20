import { durationMs } from '../duration'
import { captureWebhook } from '../generator/traffic'
import { Card, Profile, stepsOf } from './schema'

export type Target = 'local' | 'dev'

const DEV_RUNS: Record<string, string[]> = {
    'drive.traffic': [captureWebhook.name],
    invariants: ['at_least_once', 'duplicate_sends'],
    measure: ['delivery_latency_ms'],
}
const DEV_CAPS = { ratePerSecond: 10, units: 2000, driveMs: 10 * 60_000, stepMs: 60_000, convergeMs: 5 * 60_000 }

function devProblems(
    { drive, invariants, measure, bars, valves, setup, convergeWithin }: Card,
    profile: Profile
): string[] {
    const shapes = drive.traffic.map(({ name }) => captureWebhook.profile.safeParse(profile.traffic[name]).data)
    const used: Record<string, string[]> = {
        'drive.traffic': drive.traffic.map(({ name }) => name),
        drive: drive.stopOnBreak ? ['stopOnBreak'] : [],
        invariants: invariants.map(({ name }) => name),
        measure: measure.map(({ name }) => name),
        bars: bars.map(({ name }) => name),
        valves: valves.map(({ valve }) => valve),
        profile: [
            ...(['settings', 'replicas'] as const).filter((key) => Object.keys(profile[key]).length > 0),
            ...(['backlog', 'load', 'host'] as const).filter((key) => profile[key] !== undefined),
            ...(shapes.some((shape) => (shape?.parks ?? 0) > 0) ? ['parks'] : []),
        ],
    }
    const rates = shapes.map((shape) => shape?.ratePerSecond ?? 0)
    const steps = stepsOf(drive)
    const peak = rates.reduce((sum, rate) => sum + rate, 0) * Math.max(...steps.map(({ scale }) => scale))
    // Rounds each step and kind the way the generator schedules them, so the cap counts the units it sends.
    const units = steps.reduce(
        (sum, { scale, fromMs, toMs }) =>
            sum + rates.reduce((stepSum, rate) => stepSum + Math.round((rate * scale * (toMs - fromMs)) / 1000), 0),
        0
    )
    return [
        ...Object.entries(used).flatMap(([where, names]) =>
            names.filter((name) => !DEV_RUNS[where]?.includes(name)).map((name) => `${where}: dev does not run ${name}`)
        ),
        ...(setup.teams === 1 ? [] : ['setup.teams: dev drives its one fixture project']),
        ...(drive.traffic.length === 1 ? [] : ['drive.traffic: dev drives one traffic entry, so offers cannot bunch']),
        ...(peak <= DEV_CAPS.ratePerSecond ? [] : [`drive: ${peak} units a second is above the dev cap`]),
        ...(units <= DEV_CAPS.units ? [] : [`drive: ${units} units is above the dev cap`]),
        ...(durationMs(drive.for) <= DEV_CAPS.driveMs ? [] : ['drive.for: dev drives for 10m at most']),
        ...(durationMs(convergeWithin) >= DEV_CAPS.convergeMs
            ? []
            : ['convergeWithin: dev allows 5m at least to converge, since receipts take minutes to become queryable']),
        ...((drive.ramp ?? []).every((step) => durationMs(step.for) >= DEV_CAPS.stepMs)
            ? []
            : ['drive.ramp: each dev step lasts 1m at least, so rounding cannot bunch offers into a burst']),
    ]
}

export function targetProblems(card: Card, profile: Profile, target: Target): string[] {
    if (target === 'dev') {
        return devProblems(card, profile)
    }
    return card.drive.traffic
        .filter(({ name }) => name === captureWebhook.name)
        .map(({ name }) => `drive.traffic: ${name} sends to a deployment, so only --target dev runs it`)
}
