import { TRAFFIC, type UnitLoad } from '../generator/traffic'
import type { Card, Host, Load, Profile } from './schema'

export type DerivedRate = { rate: string; from: string[]; profileTarget: number; share: number; target: number }

export type DerivedLoad = Load & { derived: DerivedRate[] }

export type AdmissionTargets = { load?: DerivedLoad; host?: Host }

type ModelledTraffic = { name: string; ratePerSecond: number; listed: number; unit: UnitLoad }

type JudgedRate = { rate: string; what: string; reaches: string; profileTarget: number; per(unit: UnitLoad): number }

type Derivation = { rate: DerivedRate; problem?: string }

function judgedRatesOf({ targets }: Load): JudgedRate[] {
    const claims = Object.entries(targets.claimsPerSecond).map(([queue, profileTarget]) => ({
        rate: `claimsPerSecond.${queue}`,
        what: `${queue} claims`,
        reaches: `the ${queue} queue`,
        profileTarget,
        per: (unit: UnitLoad) => unit.claims[queue as keyof UnitLoad['claims']],
    }))
    const { newJobsPerSecond } = targets
    return newJobsPerSecond === undefined
        ? claims
        : [
              ...claims,
              {
                  rate: 'newJobsPerSecond',
                  what: 'new jobs',
                  reaches: 'new jobs',
                  profileTarget: newJobsPerSecond,
                  per: (unit) => unit.newJobs,
              },
          ]
}

function modelledTrafficOf(card: Card, profile: Profile): { traffic: ModelledTraffic[]; problems: string[] } {
    const listed = card.drive.traffic.map(({ name }) => name)
    const traffic: ModelledTraffic[] = []
    const problems: string[] = []
    for (const [name, shape] of Object.entries(profile.traffic)) {
        const kind = TRAFFIC.find((known) => known.name === name)
        const parsed = kind?.profile.safeParse(shape).data
        const unit = parsed && kind?.unitLoad?.(parsed.parks)
        if (unit === undefined) {
            problems.push(
                `profile.traffic.${name}: load admission cannot derive targets from ${name}, since its claims per unit are not modelled`
            )
            continue
        }
        const times = listed.filter((listedName) => listedName === name).length
        traffic.push({ name, ratePerSecond: parsed!.ratePerSecond, listed: times, unit })
    }
    return { traffic, problems }
}

function derivationOf(card: Card, traffic: ModelledTraffic[], judged: JudgedRate): Derivation {
    const { rate, what, reaches, profileTarget, per } = judged
    const full = traffic.reduce((sum, kind) => sum + kind.ratePerSecond * per(kind.unit), 0)
    const driven = traffic.reduce((sum, kind) => sum + kind.listed * kind.ratePerSecond * per(kind.unit), 0)
    const share = full > 0 ? driven / full : 0
    const from = traffic.filter((kind) => kind.listed > 0 && per(kind.unit) > 0).map(({ name }) => name)
    const names = [...new Set(card.drive.traffic.map(({ name }) => name))].join(', ')
    const problem =
        full === 0
            ? `profile.load.targets.${rate}: the profile's traffic makes no ${what}, so no card can derive this target`
            : driven === 0
              ? `drive.traffic: ${names} makes no ${what}, and load admission would judge the card on them (profile.load.targets.${rate}); drive traffic that reaches ${reaches}, or run the card on a profile without that target`
              : undefined
    return { rate: { rate, from, profileTarget, share, target: profileTarget * share }, problem }
}

export function loadTargetsOf(card: Card, profile: Profile): { load?: DerivedLoad; problems: string[] } {
    if (profile.load === undefined) {
        return { problems: [] }
    }
    const { traffic, problems } = modelledTrafficOf(card, profile)
    if (problems.length > 0) {
        return { problems }
    }
    const judged = judgedRatesOf(profile.load)
    const derivations = judged.map((rate) => derivationOf(card, traffic, rate))
    const targetOf = (rate: string): number =>
        derivations.find((derivation) => derivation.rate.rate === rate)!.rate.target
    const { claimsPerSecond, newJobsPerSecond } = profile.load.targets
    return {
        load: {
            ...profile.load,
            targets: {
                claimsPerSecond: Object.fromEntries(
                    Object.keys(claimsPerSecond).map((queue) => [queue, targetOf(`claimsPerSecond.${queue}`)])
                ),
                ...(newJobsPerSecond === undefined ? {} : { newJobsPerSecond: targetOf('newJobsPerSecond') }),
            },
            derived: derivations.map(({ rate }) => rate),
        },
        problems: derivations.flatMap(({ problem }) => (problem === undefined ? [] : [problem])),
    }
}
