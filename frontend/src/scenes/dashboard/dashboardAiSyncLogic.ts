import { parseToolOutputRecord, resolveToolCall } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/types/streamTypes'

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
        if (
            requestedTileIds.some((id) => id === null) ||
            !returned.valid ||
            requestedTileIds.length !== returned.tileIds.length ||
            requestedTileIds.some((id, index) => id !== returned.tileIds[index])
        ) {
            return null
        }
        return candidate('dashboard', target.dashboardId, requestedTileIds as number[])
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
    if (!records || records.length === 0) {
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
        if (
            requestedDashboards === null ||
            (requestedDashboards !== undefined && !requestedDashboards.includes(target.dashboardId)) ||
            !responseTiles
        ) {
            return { candidate: null, ownership: knownOwnership }
        }
        const matchingTiles = responseTiles.filter((tile) => tile.dashboardId === target.dashboardId)
        if (matchingTiles.length !== 1) {
            return { candidate: null, ownership: knownOwnership }
        }
        const dashboardIds = sortedUniqueNumbers(responseTiles.map((tile) => tile.dashboardId))
        return {
            candidate: candidate('insight', target.dashboardId, [matchingTiles[0].tileId], identity.identifiers),
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
    if (knownDashboardId !== undefined && outputDashboardId !== undefined && knownDashboardId !== outputDashboardId) {
        return { candidate: null, ownership: knownOwnership }
    }
    const ownedDashboardId = outputDashboardId ?? knownDashboardId
    if (
        ownedDashboardId === undefined ||
        ownedDashboardId !== target.dashboardId ||
        (toolName === 'subscriptions-create' && requestDashboardId !== ownedDashboardId)
    ) {
        return { candidate: null, ownership: knownOwnership }
    }

    const subscriptionDashboardById = { ...knownOwnership.subscriptionDashboardById }
    if (toolName === 'subscriptions-delete') {
        delete subscriptionDashboardById[subscriptionId]
    } else {
        subscriptionDashboardById[subscriptionId] = ownedDashboardId
    }
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

function alertInsightIdentity(output: Record<string, unknown>): InsightIdentity | null | undefined {
    const hasNumericId = Object.prototype.hasOwnProperty.call(output, 'insight')
    const hasShortId = Object.prototype.hasOwnProperty.call(output, 'insight_short_id')
    if (!hasNumericId && !hasShortId) {
        return undefined
    }
    const numericId = hasNumericId ? asPositiveSafeInteger(output.insight) : null
    const shortId = hasShortId ? asNonEmptyString(output.insight_short_id) : null
    if ((hasNumericId && numericId === null) || (hasShortId && shortId === null)) {
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

    const learnedInsightKey = knownOwnership.alertInsightById[alertId]
    const evidence: InsightIdentifier[] = [
        ...(requestInsightId === undefined ? [] : [requestInsightId]),
        ...(responseIdentity === undefined ? [] : responseIdentity.identifiers),
        ...(learnedInsightKey === undefined ? [] : [asInsightIdentifier(learnedInsightKey)!]),
    ]
    let ownedInsight = resolveTargetInsight(target, evidence)
    if (!ownedInsight && toolName === 'alert-delete' && evidence.length === 0) {
        ownedInsight = targetInsightForAlertId(target, alertId)
    }
    if (!ownedInsight) {
        return { candidate: null, ownership: knownOwnership }
    }

    const alertInsightById = { ...knownOwnership.alertInsightById }
    const canonicalInsightKey = ownedInsight.numericId === null ? ownedInsight.shortId : String(ownedInsight.numericId)
    if (!canonicalInsightKey) {
        return { candidate: null, ownership: knownOwnership }
    }
    if (toolName === 'alert-delete') {
        const owningTile = target.tiles.find((tile) => tile.tileId === ownedInsight!.tileId)
        for (const currentAlertId of owningTile?.alertIds ?? []) {
            const currentAlertKey = asResourceKey(currentAlertId)
            if (currentAlertKey) {
                alertInsightById[currentAlertKey] = canonicalInsightKey
            }
        }
        delete alertInsightById[alertId]
    } else {
        alertInsightById[alertId] = canonicalInsightKey
    }
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
    const parsedOutput = parseToolOutputRecord(event.invocation.output, event.invocation.input)
    const hasEmptyAlertDeleteOutput =
        event.toolName === 'alert-delete' &&
        (event.invocation.output === null ||
            event.invocation.output === undefined ||
            (typeof event.invocation.output === 'string' && !event.invocation.output.trim()))
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
