import { LogicWrapper, MakeLogicType, actions, kea, key, listeners, path, props, reducers } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { DashboardType, QueryBasedInsightModel } from '~/types'

import { insightAlertsLogic } from 'products/alerts/frontend/logic/insightAlertsLogic'
import { parseToolOutputRecord, resolveToolCall } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/types/streamTypes'
import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'

import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'

const TRANSIENT_HIGHLIGHT_DURATION_MS = 3000

export const DASHBOARD_AI_MUTATION_TOOLS = [
    'alert-create',
    'alert-delete',
    'alert-update',
    'dashboard-create-text-tile',
    'dashboard-create-tile',
    'dashboard-delete',
    'dashboard-delete-tile',
    'dashboard-reorder-tiles',
    'dashboard-tile-copy',
    'dashboard-update',
    'dashboard-update-text-tile',
    'dashboard-widgets-batch-add',
    'dashboard-widgets-batch-update',
    'dashboards-copy-tile-create',
    'dashboards-move-tile-create',
    'dashboards-move-tile-partial-update',
    'dashboards-update',
    'dashboards-widgets-batch-create',
    'insight-create',
    'insight-delete',
    'insight-update',
    'subscriptions-create',
    'subscriptions-delete',
    'subscriptions-partial-update',
] as const

export type DashboardAiToolFamily = 'dashboard' | 'insight' | 'subscription' | 'alert'

export interface DashboardAiSyncCandidate {
    family: DashboardAiToolFamily
    dashboardId: number
    tileIds: number[]
    insightIds: Array<number | string>
    deletesDashboard: boolean
}

export interface DashboardAiSyncTarget {
    dashboardId: number
    tiles: Array<{
        tileId: number
        insightId: number | null
        insightShortId: string | null
        alertIds: Array<number | string>
    }>
}

export interface DashboardAiKnownOwnership {
    subscriptionDashboardById: Record<number, number>
    insightDashboardsById: Record<string, number[]>
    alertInsightById: Record<string, string>
}

export interface DashboardAiMutationResolution {
    candidate: DashboardAiSyncCandidate | null
    ownership: DashboardAiKnownOwnership
}

export interface DashboardAiSyncBatch {
    families: DashboardAiToolFamily[]
    tileIds: number[]
    insightIds: Array<number | string>
    queuedEventCount: number
    startedAt: number
}

export interface DashboardAiSyncLogicProps {
    dashboardId: number
}

type InsightIdentifier = number | string

interface DashboardEvidence {
    valid: boolean
    dashboardId: number | null
}

interface InsightIdentity {
    numericId: number | null
    shortId: string | null
    identifiers: InsightIdentifier[]
}

interface TargetInsight {
    tileId: number
    numericId: number | null
    shortId: string | null
}

const DASHBOARD_TOOLS = new Set<string>([
    'dashboard-update',
    'dashboard-create-tile',
    'dashboard-create-text-tile',
    'dashboard-update-text-tile',
    'dashboard-delete-tile',
    'dashboard-reorder-tiles',
    'dashboard-tile-copy',
    'dashboard-widgets-batch-add',
    'dashboard-widgets-batch-update',
    'dashboards-widgets-batch-create',
    'dashboards-copy-tile-create',
    'dashboards-move-tile-create',
    'dashboards-move-tile-partial-update',
    'dashboards-update',
    'dashboard-delete',
])
const MOVE_TOOLS = new Set(['dashboards-move-tile-create', 'dashboards-move-tile-partial-update'])
const DASHBOARD_RESPONSE_TOOLS = new Set([
    'dashboard-update',
    'dashboards-update',
    'dashboard-reorder-tiles',
    'dashboard-tile-copy',
    'dashboards-copy-tile-create',
    'dashboard-delete',
])
const TILE_CREATE_TOOLS = new Set(['dashboard-create-tile', 'dashboard-create-text-tile'])
const BATCH_ADD_TOOLS = new Set(['dashboard-widgets-batch-add', 'dashboards-widgets-batch-create'])

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function asRecordArray(value: unknown): Record<string, unknown>[] | null {
    if (!Array.isArray(value)) {
        return null
    }
    const records = value.map(asRecord)
    return records.every((record): record is Record<string, unknown> => record !== null) ? records : null
}

function isEmptyRecord(value: unknown): boolean {
    const record = asRecord(value)
    return record !== null && Object.keys(record).length === 0
}

function isEmptyAlertDeleteOutput(value: unknown): boolean {
    if (value === null || value === undefined || isEmptyRecord(value)) {
        return true
    }
    if (typeof value !== 'string') {
        return false
    }
    const trimmed = value.trim()
    if (!trimmed) {
        return true
    }
    try {
        return isEmptyRecord(JSON.parse(trimmed))
    } catch {
        return false
    }
}

function asPositiveSafeInteger(value: unknown): number | null {
    const parsed = typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : value
    return typeof parsed === 'number' && Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

function asNonEmptyString(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

function asResourceKey(value: unknown): string | null {
    const numericId = asPositiveSafeInteger(value)
    if (numericId !== null) {
        return String(numericId)
    }
    return asNonEmptyString(value)
}

function asInsightIdentifier(value: unknown): InsightIdentifier | null {
    const numericId = asPositiveSafeInteger(value)
    return numericId ?? asNonEmptyString(value)
}

function getAgreedPositiveSafeInteger(
    record: Record<string, unknown>,
    keys: readonly string[]
): number | null | undefined {
    const present = keys.filter((key) => Object.prototype.hasOwnProperty.call(record, key))
    if (present.length === 0) {
        return undefined
    }
    const values = present.map((key) => asPositiveSafeInteger(record[key]))
    if (values.some((value) => value === null)) {
        return null
    }
    return values.every((value) => value === values[0]) ? values[0]! : null
}

function getAgreedResourceKey(record: Record<string, unknown>, keys: readonly string[]): string | null | undefined {
    const present = keys.filter((key) => Object.prototype.hasOwnProperty.call(record, key))
    if (present.length === 0) {
        return undefined
    }
    const values = present.map((key) => asResourceKey(record[key]))
    if (values.some((value) => value === null)) {
        return null
    }
    return values.every((value) => value === values[0]) ? values[0]! : null
}

function getAgreedInsightIdentifier(
    record: Record<string, unknown>,
    keys: readonly string[]
): InsightIdentifier | null | undefined {
    const present = keys.filter((key) => Object.prototype.hasOwnProperty.call(record, key))
    if (present.length === 0) {
        return undefined
    }
    const values = present.map((key) => asInsightIdentifier(record[key]))
    if (values.some((value) => value === null)) {
        return null
    }
    return values.every((value) => value === values[0]) ? values[0]! : null
}

function sortedUniqueNumbers(values: number[]): number[] {
    return [...new Set(values)].sort((a, b) => a - b)
}

function sortedUniqueInsightIds(values: InsightIdentifier[]): InsightIdentifier[] {
    return [...new Set(values)].sort((a, b) => {
        if (typeof a === 'number' && typeof b === 'string') {
            return -1
        }
        if (typeof a === 'string' && typeof b === 'number') {
            return 1
        }
        return typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b))
    })
}

function candidate(
    family: DashboardAiToolFamily,
    dashboardId: number,
    tileIds: number[] = [],
    insightIds: InsightIdentifier[] = [],
    deletesDashboard = false
): DashboardAiSyncCandidate {
    return {
        family,
        dashboardId,
        tileIds: sortedUniqueNumbers(tileIds),
        insightIds: sortedUniqueInsightIds(insightIds),
        deletesDashboard,
    }
}

function dashboardIdFromUrl(value: unknown): number | null {
    if (typeof value !== 'string') {
        return null
    }
    try {
        const url = new URL(value)
        if (url.protocol !== 'http:' && url.protocol !== 'https:') {
            return null
        }
        const match = /^\/project\/(\d+)\/dashboard\/(\d+)\/?$/.exec(url.pathname)
        if (!match || asPositiveSafeInteger(match[1]) === null) {
            return null
        }
        return asPositiveSafeInteger(match[2])
    } catch {
        return null
    }
}

function collectDashboardEvidence(
    output: Record<string, unknown>,
    responseIdIsDashboardId: boolean
): DashboardEvidence {
    const evidence: number[] = []
    const directKeys = responseIdIsDashboardId ? ['id', 'dashboard_id', 'dashboardId'] : ['dashboard_id', 'dashboardId']
    const direct = getAgreedPositiveSafeInteger(output, directKeys)
    if (direct === null) {
        return { valid: false, dashboardId: null }
    }
    if (direct !== undefined) {
        evidence.push(direct)
    }

    if (Object.prototype.hasOwnProperty.call(output, 'dashboard')) {
        const nested = asRecord(output.dashboard)
        const nestedId = nested ? getAgreedPositiveSafeInteger(nested, ['id']) : asPositiveSafeInteger(output.dashboard)
        if (nestedId === null || nestedId === undefined) {
            return { valid: false, dashboardId: null }
        }
        evidence.push(nestedId)
    }

    if (Object.prototype.hasOwnProperty.call(output, '_posthogUrl')) {
        const urlId = dashboardIdFromUrl(output._posthogUrl)
        if (urlId === null) {
            return { valid: false, dashboardId: null }
        }
        evidence.push(urlId)
    }

    if (evidence.length === 0 || !evidence.every((id) => id === evidence[0])) {
        return { valid: false, dashboardId: null }
    }
    return { valid: true, dashboardId: evidence[0]! }
}

function parseDashboardTileIds(
    output: Record<string, unknown>,
    expectedDashboardId: number
): { valid: boolean; tileIds: number[] } {
    const tiles = asRecordArray(output.tiles)
    if (!tiles) {
        return { valid: false, tileIds: [] }
    }
    const tileIds: number[] = []
    for (const tile of tiles) {
        const tileId = getAgreedPositiveSafeInteger(tile, ['id', 'tile_id', 'tileId'])
        const tileDashboardId = getAgreedPositiveSafeInteger(tile, ['dashboard_id', 'dashboardId'])
        if (tileId === null || tileId === undefined || tileDashboardId === null) {
            return { valid: false, tileIds: [] }
        }
        if (tileDashboardId !== undefined && tileDashboardId !== expectedDashboardId) {
            return { valid: false, tileIds: [] }
        }
        tileIds.push(tileId)
    }
    return { valid: true, tileIds }
}

function resolveDashboardMutation(
    target: DashboardAiSyncTarget,
    toolName: string,
    input: Record<string, unknown>,
    output: Record<string, unknown>
): DashboardAiSyncCandidate | null {
    const requestedDashboardId = getAgreedPositiveSafeInteger(input, ['id', 'dashboard_id', 'dashboardId'])
    if (requestedDashboardId === null || requestedDashboardId === undefined) {
        return null
    }

    if (MOVE_TOOLS.has(toolName)) {
        const destinationDashboardId = getAgreedPositiveSafeInteger(input, ['to_dashboard', 'toDashboard'])
        const tile = asRecord(input.tile)
        const tileId = tile ? getAgreedPositiveSafeInteger(tile, ['id', 'tile_id', 'tileId']) : null
        const evidence = collectDashboardEvidence(output, true)
        if (
            destinationDashboardId === null ||
            destinationDashboardId === undefined ||
            tileId === null ||
            tileId === undefined ||
            !evidence.valid ||
            ![requestedDashboardId, destinationDashboardId].includes(evidence.dashboardId!) ||
            ![requestedDashboardId, destinationDashboardId].includes(target.dashboardId)
        ) {
            return null
        }
        return candidate('dashboard', target.dashboardId, [tileId])
    }

    if (requestedDashboardId !== target.dashboardId) {
        return null
    }

    const responseIdIsDashboardId = DASHBOARD_RESPONSE_TOOLS.has(toolName)
    const evidence = collectDashboardEvidence(output, responseIdIsDashboardId)
    if (!evidence.valid || evidence.dashboardId !== requestedDashboardId) {
        return null
    }

    if (TILE_CREATE_TOOLS.has(toolName)) {
        const tileId = getAgreedPositiveSafeInteger(output, ['id', 'tile_id', 'tileId'])
        return tileId === null || tileId === undefined ? null : candidate('dashboard', target.dashboardId, [tileId])
    }

    if (toolName === 'dashboard-update-text-tile') {
        const requestedTileId = getAgreedPositiveSafeInteger(input, ['tile_id', 'tileId'])
        const responseTileId = getAgreedPositiveSafeInteger(output, ['id', 'tile_id', 'tileId'])
        return requestedTileId === null ||
            requestedTileId === undefined ||
            responseTileId === null ||
            responseTileId === undefined ||
            requestedTileId !== responseTileId
            ? null
            : candidate('dashboard', target.dashboardId, [responseTileId])
    }

    if (toolName === 'dashboard-delete-tile') {
        const tileId = getAgreedPositiveSafeInteger(input, ['tile_id', 'tileId'])
        return tileId === null || tileId === undefined ? null : candidate('dashboard', target.dashboardId, [tileId])
    }

    if (toolName === 'dashboard-reorder-tiles') {
        if (!Array.isArray(input.tile_order) || input.tile_order.length === 0) {
            return null
        }
        const requestedTileIds = input.tile_order.map(asPositiveSafeInteger)
        const returned = parseDashboardTileIds(output, requestedDashboardId)
        const validRequestedTileIds = requestedTileIds.filter((id): id is number => id !== null)
        const returnedTileIds = new Set(returned.tileIds)
        if (
            validRequestedTileIds.length !== requestedTileIds.length ||
            new Set(validRequestedTileIds).size !== validRequestedTileIds.length ||
            !returned.valid ||
            returnedTileIds.size !== returned.tileIds.length ||
            validRequestedTileIds.some((id) => !returnedTileIds.has(id))
        ) {
            return null
        }
        return candidate('dashboard', target.dashboardId, validRequestedTileIds)
    }

    if (BATCH_ADD_TOOLS.has(toolName) || toolName === 'dashboard-widgets-batch-update') {
        const requestedWidgets = asRecordArray(input.widgets)
        const returned = parseDashboardTileIds(output, requestedDashboardId)
        if (
            !requestedWidgets ||
            requestedWidgets.length === 0 ||
            !returned.valid ||
            requestedWidgets.length !== returned.tileIds.length
        ) {
            return null
        }
        if (toolName === 'dashboard-widgets-batch-update') {
            const requestedTileIds = requestedWidgets.map((widget) =>
                getAgreedPositiveSafeInteger(widget, ['tile_id', 'tileId'])
            )
            if (
                requestedTileIds.some((id) => id === null || id === undefined) ||
                requestedTileIds.some((id, index) => id !== returned.tileIds[index])
            ) {
                return null
            }
        }
        return candidate('dashboard', target.dashboardId, returned.tileIds)
    }

    if (toolName === 'dashboard-delete') {
        return candidate('dashboard', target.dashboardId, [], [], true)
    }

    return candidate('dashboard', target.dashboardId)
}

function parseOutputInsightIdentity(output: Record<string, unknown>): InsightIdentity | null {
    const hasNumericId = Object.prototype.hasOwnProperty.call(output, 'id')
    const hasShortId = Object.prototype.hasOwnProperty.call(output, 'short_id')
    const numericId = hasNumericId ? asPositiveSafeInteger(output.id) : null
    const shortId = hasShortId ? asNonEmptyString(output.short_id) : null
    if ((hasNumericId && numericId === null) || (hasShortId && shortId === null) || (!hasNumericId && !hasShortId)) {
        return null
    }
    return {
        numericId,
        shortId,
        identifiers: sortedUniqueInsightIds([
            ...(numericId === null ? [] : [numericId]),
            ...(shortId === null ? [] : [shortId]),
        ]),
    }
}

function tileMatchesIdentifier(tile: DashboardAiSyncTarget['tiles'][number], identifier: InsightIdentifier): boolean {
    return typeof identifier === 'number' ? tile.insightId === identifier : tile.insightShortId === identifier
}

function resolveTargetInsight(target: DashboardAiSyncTarget, identifiers: InsightIdentifier[]): TargetInsight | null {
    if (identifiers.length === 0) {
        return null
    }
    let matchedTile: DashboardAiSyncTarget['tiles'][number] | null = null
    for (const identifier of identifiers) {
        const matches = target.tiles.filter((tile) => tileMatchesIdentifier(tile, identifier))
        if (matches.length !== 1 || (matchedTile && matchedTile.tileId !== matches[0].tileId)) {
            return null
        }
        matchedTile = matches[0]
    }
    return matchedTile
        ? { tileId: matchedTile.tileId, numericId: matchedTile.insightId, shortId: matchedTile.insightShortId }
        : null
}

function identifiersForTargetInsight(insight: TargetInsight): InsightIdentifier[] {
    return sortedUniqueInsightIds([
        ...(insight.numericId === null ? [] : [insight.numericId]),
        ...(insight.shortId === null ? [] : [insight.shortId]),
    ])
}

function identitiesAgreeWithTarget(
    target: DashboardAiSyncTarget,
    identity: InsightIdentity,
    requestIdentifier?: InsightIdentifier
): boolean {
    const outputMatches = identity.identifiers.flatMap((identifier) =>
        target.tiles.filter((tile) => tileMatchesIdentifier(tile, identifier))
    )
    if (outputMatches.length > 0 && !resolveTargetInsight(target, identity.identifiers)) {
        return false
    }
    if (requestIdentifier === undefined) {
        return true
    }
    if (identity.identifiers.includes(requestIdentifier)) {
        return true
    }
    const requestTarget = resolveTargetInsight(target, [requestIdentifier])
    const responseTarget = resolveTargetInsight(target, identity.identifiers)
    return requestTarget !== null && responseTarget !== null && requestTarget.tileId === responseTarget.tileId
}

function parseAuthoritativeDashboardTiles(
    output: Record<string, unknown>
): Array<{ tileId: number; dashboardId: number }> | null {
    const records = asRecordArray(output.dashboard_tiles)
    if (!records) {
        return null
    }
    const activeTiles: Array<{ tileId: number; dashboardId: number }> = []
    for (const record of records) {
        const tileId = getAgreedPositiveSafeInteger(record, ['id'])
        const dashboardId = getAgreedPositiveSafeInteger(record, ['dashboard_id', 'dashboardId'])
        if (
            tileId === null ||
            tileId === undefined ||
            dashboardId === null ||
            dashboardId === undefined ||
            !Object.prototype.hasOwnProperty.call(record, 'deleted') ||
            ![true, false, null].includes(record.deleted as boolean | null)
        ) {
            return null
        }
        if (record.deleted === false || record.deleted === null) {
            activeTiles.push({ tileId, dashboardId })
        }
    }
    return activeTiles
}

function requestDashboardMembership(input: Record<string, unknown>): number[] | null | undefined {
    if (!Object.prototype.hasOwnProperty.call(input, 'dashboards')) {
        return undefined
    }
    if (!Array.isArray(input.dashboards)) {
        return null
    }
    const ids = input.dashboards.map(asPositiveSafeInteger)
    return ids.some((id) => id === null) ? null : sortedUniqueNumbers(ids as number[])
}

function learnInsightOwnership(
    knownOwnership: DashboardAiKnownOwnership,
    identity: InsightIdentity,
    dashboardIds: number[]
): DashboardAiKnownOwnership {
    const insightDashboardsById = { ...knownOwnership.insightDashboardsById }
    for (const identifier of identity.identifiers) {
        insightDashboardsById[String(identifier)] = sortedUniqueNumbers(dashboardIds)
    }
    return { ...knownOwnership, insightDashboardsById }
}

function sameDashboardMembership(left: number[], right: number[]): boolean {
    return left.length === right.length && left.every((dashboardId, index) => dashboardId === right[index])
}

function resolveInsightMutation(
    target: DashboardAiSyncTarget,
    knownOwnership: DashboardAiKnownOwnership,
    toolName: string,
    input: Record<string, unknown>,
    output: Record<string, unknown>
): DashboardAiMutationResolution {
    const identity = parseOutputInsightIdentity(output)
    if (!identity) {
        return { candidate: null, ownership: knownOwnership }
    }
    const requestIdentifier = getAgreedInsightIdentifier(input, [
        'id',
        'insight_id',
        'insightId',
        'short_id',
        'shortId',
    ])
    if (requestIdentifier === null || !identitiesAgreeWithTarget(target, identity, requestIdentifier)) {
        return { candidate: null, ownership: knownOwnership }
    }

    if (toolName === 'insight-create' || toolName === 'insight-update') {
        if (toolName === 'insight-update' && requestIdentifier === undefined) {
            return { candidate: null, ownership: knownOwnership }
        }
        const requestedDashboards = requestDashboardMembership(input)
        const responseTiles = parseAuthoritativeDashboardTiles(output)
        if (requestedDashboards === null || !responseTiles) {
            return { candidate: null, ownership: knownOwnership }
        }
        const dashboardIds = sortedUniqueNumbers(responseTiles.map((tile) => tile.dashboardId))
        if (requestedDashboards !== undefined && !sameDashboardMembership(requestedDashboards, dashboardIds)) {
            return { candidate: null, ownership: knownOwnership }
        }
        const matchingTiles = responseTiles.filter((tile) => tile.dashboardId === target.dashboardId)
        if (matchingTiles.length > 1) {
            return { candidate: null, ownership: knownOwnership }
        }
        const currentTarget = resolveTargetInsight(target, identity.identifiers)
        const wasKnownOnTarget = identity.identifiers.some((identifier) =>
            knownOwnership.insightDashboardsById[String(identifier)]?.includes(target.dashboardId)
        )
        if (
            matchingTiles.length === 0 &&
            (toolName !== 'insight-update' ||
                requestedDashboards === undefined ||
                (!currentTarget && !wasKnownOnTarget))
        ) {
            return { candidate: null, ownership: knownOwnership }
        }
        return {
            candidate: candidate(
                'insight',
                target.dashboardId,
                matchingTiles.length === 1 ? [matchingTiles[0].tileId] : [],
                identity.identifiers
            ),
            ownership: learnInsightOwnership(knownOwnership, identity, dashboardIds),
        }
    }

    if (requestIdentifier === undefined) {
        return { candidate: null, ownership: knownOwnership }
    }
    const currentTarget = resolveTargetInsight(target, identity.identifiers)
    const identifiers = currentTarget ? identifiersForTargetInsight(currentTarget) : identity.identifiers
    const isKnownOnDashboard = identifiers.some((identifier) =>
        knownOwnership.insightDashboardsById[String(identifier)]?.includes(target.dashboardId)
    )
    if (!currentTarget && !isKnownOnDashboard) {
        return { candidate: null, ownership: knownOwnership }
    }
    const insightDashboardsById = { ...knownOwnership.insightDashboardsById }
    for (const identifier of identifiers) {
        delete insightDashboardsById[String(identifier)]
    }
    return {
        candidate: candidate('insight', target.dashboardId, currentTarget ? [currentTarget.tileId] : [], identifiers),
        ownership: { ...knownOwnership, insightDashboardsById },
    }
}

function resolveSubscriptionMutation(
    target: DashboardAiSyncTarget,
    knownOwnership: DashboardAiKnownOwnership,
    toolName: string,
    input: Record<string, unknown>,
    output: Record<string, unknown>
): DashboardAiMutationResolution {
    const requestId = getAgreedPositiveSafeInteger(input, ['id', 'subscription_id', 'subscriptionId'])
    const outputId = getAgreedPositiveSafeInteger(output, ['id', 'subscription_id', 'subscriptionId'])
    const subscriptionId = toolName === 'subscriptions-create' ? outputId : requestId
    if (
        subscriptionId === null ||
        subscriptionId === undefined ||
        outputId === null ||
        (outputId !== undefined && outputId !== subscriptionId)
    ) {
        return { candidate: null, ownership: knownOwnership }
    }

    const requestDashboardId = getAgreedPositiveSafeInteger(input, ['dashboard', 'dashboard_id', 'dashboardId'])
    const outputDashboardId = getAgreedPositiveSafeInteger(output, ['dashboard', 'dashboard_id', 'dashboardId'])
    if (
        requestDashboardId === null ||
        outputDashboardId === null ||
        (requestDashboardId !== undefined &&
            outputDashboardId !== undefined &&
            requestDashboardId !== outputDashboardId)
    ) {
        return { candidate: null, ownership: knownOwnership }
    }
    const knownDashboardId = knownOwnership.subscriptionDashboardById[subscriptionId]
    const subscriptionDashboardById = { ...knownOwnership.subscriptionDashboardById }
    if (toolName === 'subscriptions-delete') {
        if (
            knownDashboardId !== undefined &&
            ((requestDashboardId !== undefined && requestDashboardId !== knownDashboardId) ||
                (outputDashboardId !== undefined && outputDashboardId !== knownDashboardId))
        ) {
            return { candidate: null, ownership: knownOwnership }
        }
        const priorDashboardId = knownDashboardId ?? outputDashboardId ?? requestDashboardId
        if (priorDashboardId !== target.dashboardId) {
            return { candidate: null, ownership: knownOwnership }
        }
        delete subscriptionDashboardById[subscriptionId]
        return {
            candidate: candidate('subscription', target.dashboardId),
            ownership: { ...knownOwnership, subscriptionDashboardById },
        }
    }

    const movesFromKnownOwner =
        knownDashboardId !== undefined &&
        ((requestDashboardId !== undefined && requestDashboardId !== knownDashboardId) ||
            (outputDashboardId !== undefined && outputDashboardId !== knownDashboardId))
    if (movesFromKnownOwner && (requestDashboardId === undefined || outputDashboardId === undefined)) {
        return { candidate: null, ownership: knownOwnership }
    }
    const postDashboardId = outputDashboardId ?? knownDashboardId
    if (
        postDashboardId === undefined ||
        (knownDashboardId !== target.dashboardId && postDashboardId !== target.dashboardId) ||
        (toolName === 'subscriptions-create' && requestDashboardId !== postDashboardId)
    ) {
        return { candidate: null, ownership: knownOwnership }
    }
    subscriptionDashboardById[subscriptionId] = postDashboardId
    return {
        candidate: candidate('subscription', target.dashboardId),
        ownership: { ...knownOwnership, subscriptionDashboardById },
    }
}

function targetInsightForAlertId(target: DashboardAiSyncTarget, alertId: string): TargetInsight | null {
    const matchingTiles = target.tiles.filter((tile) => tile.alertIds.some((id) => asResourceKey(id) === alertId))
    if (matchingTiles.length !== 1) {
        return null
    }
    const tile = matchingTiles[0]
    return { tileId: tile.tileId, numericId: tile.insightId, shortId: tile.insightShortId }
}

function parseAlertInsightField(value: unknown): InsightIdentity | null {
    const nested = asRecord(value)
    if (nested !== null) {
        return parseOutputInsightIdentity(nested)
    }
    const numericId = asPositiveSafeInteger(value)
    return numericId === null ? null : { numericId, shortId: null, identifiers: [numericId] }
}

function alertInsightIdentity(output: Record<string, unknown>): InsightIdentity | null | undefined {
    const hasInsight = Object.prototype.hasOwnProperty.call(output, 'insight')
    const hasShortId = Object.prototype.hasOwnProperty.call(output, 'insight_short_id')
    if (!hasInsight && !hasShortId) {
        return undefined
    }
    // The alert serializer replaces `insight` with the full insight object in every response, so
    // the identity arrives nested even though the generated type declares a bare ID.
    const insight = hasInsight ? parseAlertInsightField(output.insight) : null
    const topShortId = hasShortId ? asNonEmptyString(output.insight_short_id) : null
    if ((hasInsight && insight === null) || (hasShortId && topShortId === null)) {
        return null
    }
    const numericId = insight?.numericId ?? null
    const nestedShortId = insight?.shortId ?? null
    if (nestedShortId !== null && topShortId !== null && nestedShortId !== topShortId) {
        return null
    }
    const shortId = nestedShortId ?? topShortId
    return {
        numericId,
        shortId,
        identifiers: sortedUniqueInsightIds([
            ...(numericId === null ? [] : [numericId]),
            ...(shortId === null ? [] : [shortId]),
        ]),
    }
}

function insightIdentifiersAgree(
    target: DashboardAiSyncTarget,
    left: InsightIdentifier,
    right: InsightIdentifier
): boolean {
    if (left === right) {
        return true
    }
    const leftTarget = resolveTargetInsight(target, [left])
    const rightTarget = resolveTargetInsight(target, [right])
    return leftTarget !== null && rightTarget !== null && leftTarget.tileId === rightTarget.tileId
}

function canonicalInsightKey(identity: InsightIdentity | undefined, fallback?: InsightIdentifier): string | null {
    if (identity?.numericId !== null && identity?.numericId !== undefined) {
        return String(identity.numericId)
    }
    return identity?.shortId ?? (fallback === undefined ? null : String(fallback))
}

function resolveAlertMutation(
    target: DashboardAiSyncTarget,
    knownOwnership: DashboardAiKnownOwnership,
    toolName: string,
    input: Record<string, unknown>,
    output: Record<string, unknown>
): DashboardAiMutationResolution {
    const requestAlertId = getAgreedResourceKey(input, ['id', 'alert_id', 'alertId'])
    const outputAlertId = getAgreedResourceKey(output, ['id', 'alert_id', 'alertId'])
    const alertId = toolName === 'alert-create' ? outputAlertId : requestAlertId
    if (
        alertId === null ||
        alertId === undefined ||
        outputAlertId === null ||
        (outputAlertId !== undefined && outputAlertId !== alertId)
    ) {
        return { candidate: null, ownership: knownOwnership }
    }

    const requestInsightId = getAgreedInsightIdentifier(input, ['insight', 'insight_id', 'insightId'])
    const responseIdentity = alertInsightIdentity(output)
    if (requestInsightId === null || responseIdentity === null) {
        return { candidate: null, ownership: knownOwnership }
    }
    if (toolName === 'alert-delete' && Object.keys(output).length > 0 && outputAlertId === undefined) {
        return { candidate: null, ownership: knownOwnership }
    }

    if (responseIdentity !== undefined && !identitiesAgreeWithTarget(target, responseIdentity, requestInsightId)) {
        return { candidate: null, ownership: knownOwnership }
    }

    const learnedInsightKey = knownOwnership.alertInsightById[alertId]
    let learnedInsightId: InsightIdentifier | undefined
    if (learnedInsightKey !== undefined) {
        const parsedLearnedInsightId = asInsightIdentifier(learnedInsightKey)
        if (parsedLearnedInsightId === null) {
            return { candidate: null, ownership: knownOwnership }
        }
        learnedInsightId = parsedLearnedInsightId
    }
    const alertInsightById = { ...knownOwnership.alertInsightById }
    if (toolName === 'alert-delete') {
        if (
            learnedInsightId !== undefined &&
            ((requestInsightId !== undefined && !insightIdentifiersAgree(target, requestInsightId, learnedInsightId)) ||
                (responseIdentity !== undefined &&
                    !identitiesAgreeWithTarget(target, responseIdentity, learnedInsightId)))
        ) {
            return { candidate: null, ownership: knownOwnership }
        }
        let ownedInsight = learnedInsightId ? resolveTargetInsight(target, [learnedInsightId]) : null
        if (learnedInsightId !== undefined && !ownedInsight) {
            return { candidate: null, ownership: knownOwnership }
        }
        ownedInsight ??= requestInsightId === undefined ? null : resolveTargetInsight(target, [requestInsightId])
        ownedInsight ??= responseIdentity ? resolveTargetInsight(target, responseIdentity.identifiers) : null
        ownedInsight ??= targetInsightForAlertId(target, alertId)
        if (!ownedInsight) {
            return { candidate: null, ownership: knownOwnership }
        }
        const ownedInsightKey = ownedInsight.numericId === null ? ownedInsight.shortId : String(ownedInsight.numericId)
        if (!ownedInsightKey) {
            return { candidate: null, ownership: knownOwnership }
        }
        const owningTile = target.tiles.find((tile) => tile.tileId === ownedInsight!.tileId)
        for (const currentAlertId of owningTile?.alertIds ?? []) {
            const currentAlertKey = asResourceKey(currentAlertId)
            if (currentAlertKey) {
                alertInsightById[currentAlertKey] = ownedInsightKey
            }
        }
        delete alertInsightById[alertId]
        return {
            candidate: candidate(
                'alert',
                target.dashboardId,
                [ownedInsight.tileId],
                identifiersForTargetInsight(ownedInsight)
            ),
            ownership: { ...knownOwnership, alertInsightById },
        }
    }

    if (learnedInsightId !== undefined) {
        const requestMovesOwner =
            requestInsightId !== undefined && !insightIdentifiersAgree(target, requestInsightId, learnedInsightId)
        const responseMovesOwner =
            responseIdentity !== undefined && !identitiesAgreeWithTarget(target, responseIdentity, learnedInsightId)
        if (
            (requestMovesOwner || responseMovesOwner) &&
            (requestInsightId === undefined || responseIdentity === undefined)
        ) {
            return { candidate: null, ownership: knownOwnership }
        }
    }

    const priorInsight = learnedInsightId ? resolveTargetInsight(target, [learnedInsightId]) : null
    const postInsight = responseIdentity
        ? resolveTargetInsight(target, responseIdentity.identifiers)
        : requestInsightId === undefined
          ? priorInsight
          : resolveTargetInsight(target, [requestInsightId])
    if (!priorInsight && !postInsight) {
        return { candidate: null, ownership: knownOwnership }
    }
    const postInsightKey = canonicalInsightKey(responseIdentity, requestInsightId ?? learnedInsightId)
    if (!postInsightKey) {
        return { candidate: null, ownership: knownOwnership }
    }
    alertInsightById[alertId] = postInsightKey
    const affectedInsights = [priorInsight, postInsight].filter((insight): insight is TargetInsight => insight !== null)
    return {
        candidate: candidate(
            'alert',
            target.dashboardId,
            affectedInsights.map((insight) => insight.tileId),
            affectedInsights.flatMap(identifiersForTargetInsight)
        ),
        ownership: { ...knownOwnership, alertInsightById },
    }
}

export function resolveDashboardAiMutation(
    target: DashboardAiSyncTarget,
    knownOwnership: DashboardAiKnownOwnership,
    event: ToolStreamEvent,
    innerInput: Record<string, unknown> | null
): DashboardAiMutationResolution {
    if (event.phase !== 'completed' || event.invocation.status !== 'completed' || !innerInput) {
        return { candidate: null, ownership: knownOwnership }
    }
    const resolved = resolveToolCall(event.invocation)
    if (resolved.innerToolName !== event.toolName) {
        return { candidate: null, ownership: knownOwnership }
    }
    const rawOutput = event.invocation.output
    const parsedOutput = parseToolOutputRecord(rawOutput, event.invocation.input)
    const hasEmptyAlertDeleteOutput = event.toolName === 'alert-delete' && isEmptyAlertDeleteOutput(rawOutput)
    if (event.toolName === 'alert-delete' && typeof rawOutput === 'string' && !hasEmptyAlertDeleteOutput) {
        return { candidate: null, ownership: knownOwnership }
    }
    if (!parsedOutput && !hasEmptyAlertDeleteOutput) {
        return { candidate: null, ownership: knownOwnership }
    }
    const output = parsedOutput ?? {}
    if (
        ['dashboard-delete', 'insight-delete', 'subscriptions-delete', 'alert-delete'].includes(event.toolName) &&
        Object.prototype.hasOwnProperty.call(output, 'deleted') &&
        output.deleted !== true
    ) {
        return { candidate: null, ownership: knownOwnership }
    }

    if (DASHBOARD_TOOLS.has(event.toolName)) {
        return {
            candidate: resolveDashboardMutation(target, event.toolName, innerInput, output),
            ownership: knownOwnership,
        }
    }
    if (
        event.toolName === 'insight-create' ||
        event.toolName === 'insight-update' ||
        event.toolName === 'insight-delete'
    ) {
        return resolveInsightMutation(target, knownOwnership, event.toolName, innerInput, output)
    }
    if (
        event.toolName === 'subscriptions-create' ||
        event.toolName === 'subscriptions-partial-update' ||
        event.toolName === 'subscriptions-delete'
    ) {
        return resolveSubscriptionMutation(target, knownOwnership, event.toolName, innerInput, output)
    }
    if (event.toolName === 'alert-create' || event.toolName === 'alert-update' || event.toolName === 'alert-delete') {
        return resolveAlertMutation(target, knownOwnership, event.toolName, innerInput, output)
    }
    return { candidate: null, ownership: knownOwnership }
}

function emptyKnownOwnership(): DashboardAiKnownOwnership {
    return {
        subscriptionDashboardById: {},
        insightDashboardsById: {},
        alertInsightById: {},
    }
}

function targetFromCommittedDashboard(
    dashboardId: number,
    dashboard: DashboardType<QueryBasedInsightModel> | null
): DashboardAiSyncTarget {
    return {
        dashboardId,
        tiles: (dashboard?.tiles ?? []).map((tile) => ({
            tileId: tile.id,
            insightId: tile.insight?.id ?? null,
            insightShortId: tile.insight?.short_id ?? null,
            alertIds: tile.insight?.alerts?.map((alert) => alert.id) ?? [],
        })),
    }
}

function batchFromCandidate(candidate: DashboardAiSyncCandidate): DashboardAiSyncBatch {
    return {
        families: [candidate.family],
        tileIds: [...candidate.tileIds],
        insightIds: [...candidate.insightIds],
        queuedEventCount: 1,
        startedAt: Date.now(),
    }
}

function mergeBatches(left: DashboardAiSyncBatch, right: DashboardAiSyncBatch): DashboardAiSyncBatch {
    return {
        families: [...new Set([...left.families, ...right.families])].sort(),
        tileIds: sortedUniqueNumbers([...left.tileIds, ...right.tileIds]),
        insightIds: sortedUniqueInsightIds([...left.insightIds, ...right.insightIds]),
        queuedEventCount: left.queuedEventCount + right.queuedEventCount,
        startedAt: Math.min(left.startedAt, right.startedAt),
    }
}

function copyBatch(batch: DashboardAiSyncBatch): DashboardAiSyncBatch {
    return {
        families: [...new Set(batch.families)].sort(),
        tileIds: sortedUniqueNumbers(batch.tileIds),
        insightIds: sortedUniqueInsightIds(batch.insightIds),
        queuedEventCount: batch.queuedEventCount,
        startedAt: batch.startedAt,
    }
}

function copyKnownOwnership(ownership: DashboardAiKnownOwnership): DashboardAiKnownOwnership {
    return {
        subscriptionDashboardById: { ...ownership.subscriptionDashboardById },
        insightDashboardsById: Object.fromEntries(
            Object.entries(ownership.insightDashboardsById).map(([insightId, dashboardIds]) => [
                insightId,
                [...dashboardIds],
            ])
        ),
        alertInsightById: { ...ownership.alertInsightById },
    }
}

function confirmedHighlightTileIds(
    batch: DashboardAiSyncBatch,
    dashboard: DashboardType<QueryBasedInsightModel> | null
): number[] {
    return sortedUniqueNumbers(
        (dashboard?.tiles ?? [])
            .filter((tile) => {
                if (batch.tileIds.includes(tile.id)) {
                    return true
                }
                const insightId = tile.insight?.id
                const insightShortId = tile.insight?.short_id
                return (
                    (insightId !== undefined && batch.insightIds.includes(insightId)) ||
                    (insightShortId !== undefined && batch.insightIds.includes(insightShortId))
                )
            })
            .map((tile) => tile.id)
    )
}

function captureDashboardAiSyncCompleted(
    batch: DashboardAiSyncBatch,
    highlightedTileCount: number,
    success: boolean
): void {
    try {
        posthog.capture('dashboard ai sync completed', {
            tool_families: [...new Set(batch.families)].sort(),
            queued_event_count: batch.queuedEventCount,
            highlighted_tile_count: highlightedTileCount,
            duration_ms: Math.max(0, Date.now() - batch.startedAt),
            success,
        })
    } catch {
        // Telemetry must not interrupt dashboard synchronization or a queued successor.
    }
}

function refreshMountedInsightAlerts(
    dashboardId: number,
    dashboard: DashboardType<QueryBasedInsightModel> | null,
    candidate: DashboardAiSyncCandidate
): void {
    for (const tile of dashboard?.tiles ?? []) {
        const insight = tile.insight
        if (!candidate.tileIds.includes(tile.id) || !insight?.id) {
            continue
        }
        const insightLogicProps = {
            dashboardItemId: insight.short_id,
            dashboardId,
            cachedInsight: insight,
        }
        insightAlertsLogic.findMounted({ insightId: insight.id, insightLogicProps })?.actions.loadAlerts()
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardAiSyncLogicValues {
    activeBatch: DashboardAiSyncBatch | null
    knownOwnership: DashboardAiKnownOwnership
    queuedBatch: DashboardAiSyncBatch | null
    transientHighlightedTileIds: number[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardAiSyncLogicActions {
    applyToolCompletion: (
        event: ToolStreamEvent,
        innerInput: Record<string, unknown> | null
    ) => {
        event: ToolStreamEvent
        innerInput: Record<string, unknown> | null
    }
    queueDashboardSync: (candidate: DashboardAiSyncCandidate) => {
        candidate: DashboardAiSyncCandidate
    }
    setActiveBatch: (batch: DashboardAiSyncBatch | null) => {
        batch: DashboardAiSyncBatch | null
    }
    setKnownOwnership: (ownership: DashboardAiKnownOwnership) => {
        ownership: DashboardAiKnownOwnership
    }
    setQueuedBatch: (batch: DashboardAiSyncBatch | null) => {
        batch: DashboardAiSyncBatch | null
    }
    setTransientHighlightedTileIds: (tileIds: number[]) => {
        tileIds: number[]
    }
    syncDashboard: (batch: DashboardAiSyncBatch) => {
        batch: DashboardAiSyncBatch
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardAiSyncLogicMeta {
    key: number
}

export type dashboardAiSyncLogicType = MakeLogicType<
    dashboardAiSyncLogicValues,
    dashboardAiSyncLogicActions,
    DashboardAiSyncLogicProps,
    dashboardAiSyncLogicMeta
>

export const dashboardAiSyncLogic: LogicWrapper<dashboardAiSyncLogicType> = kea<dashboardAiSyncLogicType>([
    props({} as DashboardAiSyncLogicProps),
    key((props) => props.dashboardId),
    path((key) => ['scenes', 'dashboard', 'dashboardAiSyncLogic', key]),
    actions({
        applyToolCompletion: (event: ToolStreamEvent, innerInput: Record<string, unknown> | null) => ({
            event,
            innerInput,
        }),
        queueDashboardSync: (candidate: DashboardAiSyncCandidate) => ({ candidate }),
        setActiveBatch: (batch: DashboardAiSyncBatch | null) => ({ batch }),
        setQueuedBatch: (batch: DashboardAiSyncBatch | null) => ({ batch }),
        setKnownOwnership: (ownership: DashboardAiKnownOwnership) => ({ ownership }),
        setTransientHighlightedTileIds: (tileIds: number[]) => ({ tileIds }),
        syncDashboard: (batch: DashboardAiSyncBatch) => ({ batch }),
    }),
    reducers({
        activeBatch: [
            null as DashboardAiSyncBatch | null,
            { setActiveBatch: (_, { batch }) => (batch ? copyBatch(batch) : null) },
        ],
        queuedBatch: [
            null as DashboardAiSyncBatch | null,
            { setQueuedBatch: (_, { batch }) => (batch ? copyBatch(batch) : null) },
        ],
        knownOwnership: [
            emptyKnownOwnership(),
            { setKnownOwnership: (_, { ownership }) => copyKnownOwnership(ownership) },
        ],
        transientHighlightedTileIds: [
            [] as number[],
            { setTransientHighlightedTileIds: (_, { tileIds }) => [...tileIds] },
        ],
    }),
    listeners(({ actions, cache, props, values }) => ({
        applyToolCompletion: ({ event, innerInput }) => {
            const dashboard = dashboardLogic({ id: props.dashboardId }).values.dashboard
            const target = targetFromCommittedDashboard(props.dashboardId, dashboard)
            const resolution = resolveDashboardAiMutation(target, values.knownOwnership, event, innerInput)
            if (!resolution.candidate) {
                return
            }

            const candidate = resolution.candidate
            if (candidate.deletesDashboard) {
                actions.setKnownOwnership(resolution.ownership)
                router.actions.push(urls.dashboards())
                return
            }
            if (candidate.family === 'subscription') {
                subscriptionsLogic.findMounted({ dashboardId: props.dashboardId })?.actions.loadAllSubscriptions()
                actions.setKnownOwnership(resolution.ownership)
                return
            }
            if (candidate.family === 'alert') {
                refreshMountedInsightAlerts(props.dashboardId, dashboard, candidate)
                actions.setKnownOwnership(resolution.ownership)
                return
            }
            actions.queueDashboardSync(candidate)
            actions.setKnownOwnership(resolution.ownership)
        },
        queueDashboardSync: ({ candidate }) => {
            const batch = batchFromCandidate(candidate)
            if (values.activeBatch) {
                actions.setQueuedBatch(values.queuedBatch ? mergeBatches(values.queuedBatch, batch) : batch)
                return
            }
            actions.setActiveBatch(batch)
            actions.syncDashboard(batch)
        },
        syncDashboard: async ({ batch }) => {
            const disposables = cache.disposables
            let confirmedTileIds: number[] = []
            let success = false
            try {
                await dashboardLogic({ id: props.dashboardId }).asyncActions.loadDashboard({
                    action: DashboardLoadAction.BackgroundUpdate,
                })

                if (disposables.isDisposed) {
                    return
                }
                const committedDashboard = dashboardLogic({ id: props.dashboardId }).values.dashboard
                confirmedTileIds = confirmedHighlightTileIds(batch, committedDashboard)
                success = true
                if (confirmedTileIds.length > 0) {
                    actions.setTransientHighlightedTileIds(
                        sortedUniqueNumbers([...values.transientHighlightedTileIds, ...confirmedTileIds])
                    )
                    cache.disposables.add(() => {
                        let active = true
                        const timer = window.setTimeout(() => {
                            if (!active) {
                                return
                            }
                            active = false
                            actions.setTransientHighlightedTileIds([])
                        }, TRANSIENT_HIGHLIGHT_DURATION_MS)
                        return () => {
                            active = false
                            window.clearTimeout(timer)
                        }
                    }, 'transientHighlightExpiry')
                }
            } catch {
                // The dashboard loader keeps the last committed dashboard visible on failure.
            } finally {
                if (!disposables.isDisposed) {
                    captureDashboardAiSyncCompleted(batch, confirmedTileIds.length, success)
                    const successor = values.queuedBatch
                    actions.setActiveBatch(null)
                    if (successor) {
                        actions.setQueuedBatch(null)
                        actions.setActiveBatch(successor)
                        actions.syncDashboard(successor)
                    }
                }
            }
        },
    })),
])
