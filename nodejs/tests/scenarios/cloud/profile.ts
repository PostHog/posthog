import { createHash } from 'crypto'
import { readFileSync } from 'fs'
import path from 'path'
import { parse } from 'yaml'
import { z } from 'zod'

import { Duration } from '../duration'

export const CAP_USD = 200
export const TTL_HOURS = 6
export const REGION = 'us-east-1'

const Usd = z.number().nonnegative()
const Name = z.string().min(1)

export const CloudProfile = z
    .object({
        name: Name,
        account: z.string().regex(/^\d{12}$/, 'a 12-digit AWS account id'),
        region: z.literal(REGION),
        baseline: z.object({ schedulerRole: Name, evidenceBucket: Name }).strict(),
        engineVersion: Name,
        writerClass: Name,
        readerAcu: z.object({ min: z.literal(1), max: z.number().int().positive() }).strict(),
        host: z.object({ class: Name, ebsGb: z.number().int().positive() }).strict(),
        runnerProfile: Name,
        admission: z
            .object({
                capUsd: z.literal(CAP_USD).optional(),
                ttlHours: z.literal(TTL_HOURS).optional(),
                teardownAllowance: Duration,
                priceList: z
                    .object({
                        version: Name,
                        feeds: z
                            .array(
                                z.object({ url: z.string().url(), sha256: z.string().regex(/^[0-9a-f]{64}$/) }).strict()
                            )
                            .min(1),
                    })
                    .strict(),
                rates: z
                    .object({
                        writerPerHour: Usd,
                        acuPerHour: Usd,
                        hostPerHour: Usd,
                        storagePerGbMonth: Usd,
                        ebsPerGbMonth: Usd,
                        logsIngestPerGb: Usd,
                        transferPerGb: Usd,
                        s3PerThousandRequests: Usd,
                    })
                    .strict(),
                allowances: z
                    .object({
                        storageGb: z.number().positive(),
                        transferGb: z.number().nonnegative(),
                        s3Requests: z.number().int().nonnegative(),
                        enhancedMonitoringEventBytes: z.number().int().positive(),
                    })
                    .strict(),
                reserve: z.object({ marginUsd: Usd }).strict(),
            })
            .strict(),
    })
    .strict()

export type CloudProfile = z.infer<typeof CloudProfile>

export type InputFile = { file: string; bytes: Buffer; sha256: string }

export type RunInputs = { profile: CloudProfile; inputs: InputFile[] }

export class CloudProfileError extends Error {
    constructor(file: string, problems: string[]) {
        super(`${file} is not a valid cloud profile:\n${problems.map((problem) => `- ${problem}`).join('\n')}`)
        this.name = 'CloudProfileError'
    }
}

function readInput(file: string, filePath: string): InputFile {
    let bytes: Buffer
    try {
        bytes = readFileSync(filePath)
    } catch (error) {
        throw new CloudProfileError(filePath, [(error as Error).message])
    }
    return { file, bytes, sha256: createHash('sha256').update(bytes).digest('hex') }
}

function parseCloudProfile(filePath: string, { bytes }: InputFile): CloudProfile {
    let raw: unknown
    try {
        raw = parse(bytes.toString('utf8'), { maxAliasCount: 0 })
    } catch (error) {
        throw new CloudProfileError(filePath, [(error as Error).message])
    }
    const parsed = CloudProfile.safeParse(raw)
    if (!parsed.success) {
        throw new CloudProfileError(
            filePath,
            parsed.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`)
        )
    }
    return parsed.data
}

export function loadCloudProfile(filePath: string): CloudProfile {
    return parseCloudProfile(filePath, readInput('cloud-profile.yaml', filePath))
}

export function loadRunInputs(filePath: string): RunInputs {
    const cloud = readInput('cloud-profile.yaml', filePath)
    const profile = parseCloudProfile(filePath, cloud)
    const runner = readInput('runner-profile.yaml', path.resolve(path.dirname(filePath), profile.runnerProfile))
    return { profile, inputs: [cloud, runner] }
}
