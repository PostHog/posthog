import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api, { ApiError, isAbortError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getMinimumEquivalentScopes, getScopeDescription } from 'lib/scopes'
import { userLogic } from 'scenes/userLogic'

import type { OrganizationBasicType, TeamBasicType, UserType } from '~/types'

export type AgenticAuthorizationFormValues = {
    scoped_organizations: string[]
    scoped_teams: number[]
    access_type: 'teams'
}

export type AgenticPendingAuth = {
    partner_name: string
    scopes: string[]
    pays_for_customers: boolean
    partner_organization_id: string | null
    partner_organization_name: string | null
}

export interface ConsentError {
    title: string
    description: string
}

const MISSING_STATE_ERROR: ConsentError = {
    title: 'Invalid request',
    description: 'Missing required state parameter.',
}

// The authorize redirect sends these codes in the `error` search param when it can't offer a project.
const CONSENT_ERRORS: Record<string, ConsentError> = {
    forbidden: {
        title: 'No project to connect',
        description:
            'You do not have access to a project in your organization, and only organization admins can create one. Ask an admin to create a project or give you access to one, then start again from the app that sent you here.',
    },
    project_limit_reached: {
        title: 'No project to connect',
        description:
            'You do not have access to a project in your organization, and it has reached its project limit. Ask an organization admin to give you access to a project, then start again from the app that sent you here.',
    },
}

const UNKNOWN_CONSENT_ERROR: ConsentError = {
    title: 'Authorization failed',
    description: 'PostHog cannot finish this authorization. Start it again from the app that sent you here.',
}

// A stuck confirm request left the button spinning with no way out, so bound it.
const CONFIRM_TIMEOUT_MS = 20000

interface ConfirmFailure {
    reason: string
    message: string
    retryable: boolean
}

type ConfirmFailureCopy = Omit<ConfirmFailure, 'reason'>

// Keyed by the `error` code in the confirm endpoint's plain { error: code } body.
const CONFIRM_FAILURES: Record<string, (partnerName: string) => ConfirmFailureCopy> = {
    expired_or_invalid_state: () => ({
        message: 'This authorization request expired. Start it again from the app that sent you here.',
        retryable: false,
    }),
    email_mismatch: () => ({
        message:
            'You are signed in with a different account than the one that started this request. Sign in with the matching account, then start again.',
        retryable: false,
    }),
    team_not_found: () => ({
        message: 'That project no longer exists. Pick a different project.',
        retryable: true,
    }),
    team_not_accessible: () => ({
        message: 'You do not have access to that project. Pick a project you can access.',
        retryable: true,
    }),
    partner_deactivated: (partnerName) => ({
        message: `${partnerName} is no longer active, so PostHog cannot finish the authorization.`,
        retryable: false,
    }),
    missing_callback: (partnerName) => ({
        message: `${partnerName} has no redirect URL set, so PostHog cannot finish. Contact ${partnerName}.`,
        retryable: false,
    }),
    consent_changed: () => ({
        message: 'This authorization request changed while the page was open. Start over to review it.',
        retryable: false,
    }),
    project_limit_reached: (partnerName) => ({
        message: `This organization has reached its project limit, so PostHog cannot create a project for ${partnerName}. Delete a project you no longer need, then try again.`,
        retryable: true,
    }),
    forbidden: (partnerName) => ({
        message: `Only organization admins can create projects in this organization. Ask an admin to connect ${partnerName}.`,
        retryable: false,
    }),
}

// Turn a confirm failure into a specific reason the user can act on. A timeout aborts the
// request before any body arrives.
function describeConfirmFailure(error: unknown, partnerName: string): ConfirmFailure {
    if (isAbortError(error)) {
        return {
            reason: 'timeout',
            message: 'Authorizing timed out. Check your connection and try again.',
            retryable: true,
        }
    }

    const code = error instanceof ApiError ? error.data?.error : undefined
    if (typeof code !== 'string') {
        return { reason: 'unknown', message: 'Something went wrong while authorizing. Try again.', retryable: true }
    }

    const describe = Object.hasOwn(CONFIRM_FAILURES, code) ? CONFIRM_FAILURES[code] : undefined
    return {
        reason: code,
        ...(describe?.(partnerName) ?? {
            message: 'Something went wrong while authorizing. Try again.',
            retryable: true,
        }),
    }
}

// The consent page emitted no client telemetry, so a hung confirm left no trace. Record the
// reason and give the user a next step: retry when it may still work, restart when it will not.
function presentConfirmFailure(failure: ConfirmFailure, onRetry: () => void): void {
    posthog.capture('agentic authorize confirm failed', {
        reason: failure.reason,
        retryable: failure.retryable,
    })
    lemonToast.error(failure.message, {
        button: failure.retryable
            ? { label: 'Try again', action: onRetry }
            : { label: 'Start over', action: () => window.location.reload() },
    })
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface agenticAuthorizeLogicValues {
    user: UserType | null // userLogic
    agenticAuthorization: AgenticAuthorizationFormValues
    agenticAuthorizationAllErrors: Record<string, any>
    agenticAuthorizationChanged: boolean
    agenticAuthorizationErrors: DeepPartialMap<AgenticAuthorizationFormValues, ValidationErrorType>
    agenticAuthorizationHasErrors: boolean
    agenticAuthorizationManualErrors: Record<string, any>
    agenticAuthorizationTouched: boolean
    agenticAuthorizationTouches: Record<string, boolean>
    agenticAuthorizationValidationErrors: DeepPartialMap<AgenticAuthorizationFormValues, ValidationErrorType>
    allOrganizations: OrganizationBasicType[]
    allTeams: TeamBasicType[] | null
    allTeamsLoading: boolean
    consentErrorCode: string | null
    filteredTeams: TeamBasicType[]
    isAgenticAuthorizationSubmitting: boolean
    isAgenticAuthorizationValid: boolean
    pageError: ConsentError | null
    partnerName: string
    partnerOrganizationName: string | null
    paysForCustomers: boolean
    pendingAuth: AgenticPendingAuth | null
    pendingAuthLoading: boolean
    scopeDescriptions: string[]
    scopes: string[]
    showAgenticAuthorizationErrors: boolean
    state: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface agenticAuthorizeLogicActions {
    cancel: () => {
        value: true
    }
    loadAllTeams: () => any
    loadAllTeamsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAllTeamsSuccess: (
        allTeams: TeamBasicType[],
        payload?: any
    ) => {
        allTeams: TeamBasicType[]
        payload?: any
    }
    loadPendingAuth: () => any
    loadPendingAuthFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPendingAuthSuccess: (
        pendingAuth: AgenticPendingAuth | null,
        payload?: any
    ) => {
        pendingAuth: AgenticPendingAuth | null
        payload?: any
    }
    resetAgenticAuthorization: (values?: AgenticAuthorizationFormValues) => {
        values?: AgenticAuthorizationFormValues
    }
    setAgenticAuthorizationManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setAgenticAuthorizationValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setAgenticAuthorizationValues: (values: DeepPartial<AgenticAuthorizationFormValues>) => {
        values: DeepPartial<AgenticAuthorizationFormValues>
    }
    setConsentErrorCode: (consentErrorCode: string | null) => {
        consentErrorCode: string | null
    }
    setState: (state: string) => {
        state: string
    }
    submitAgenticAuthorization: () => {
        value: boolean
    }
    submitAgenticAuthorizationFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitAgenticAuthorizationRequest: (agenticAuthorization: AgenticAuthorizationFormValues) => {
        agenticAuthorization: AgenticAuthorizationFormValues
    }
    submitAgenticAuthorizationSuccess: (agenticAuthorization: AgenticAuthorizationFormValues) => {
        agenticAuthorization: AgenticAuthorizationFormValues
    }
    touchAgenticAuthorizationField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface agenticAuthorizeLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        pageError: (state: string, consentErrorCode: string | null) => ConsentError | null
        allOrganizations: (user: UserType | null) => OrganizationBasicType[]
        filteredTeams: (
            allTeams: TeamBasicType[] | null,
            agenticAuthorization: AgenticAuthorizationFormValues
        ) => TeamBasicType[]
        partnerName: (pendingAuth: AgenticPendingAuth | null) => string
        paysForCustomers: (pendingAuth: AgenticPendingAuth | null) => boolean
        partnerOrganizationName: (pendingAuth: AgenticPendingAuth | null) => string | null
        scopes: (pendingAuth: AgenticPendingAuth | null) => string[]
        scopeDescriptions: (scopes: string[]) => string[]
    }
}

export type agenticAuthorizeLogicType = MakeLogicType<
    agenticAuthorizeLogicValues,
    agenticAuthorizeLogicActions,
    Record<string, any>,
    agenticAuthorizeLogicMeta
>

export const agenticAuthorizeLogic = kea<agenticAuthorizeLogicType>([
    path(['agentic', 'authorize']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        setState: (state: string) => ({ state }),
        setConsentErrorCode: (consentErrorCode: string | null) => ({ consentErrorCode }),
        cancel: true,
    }),
    loaders(({ values }) => ({
        allTeams: [
            null as TeamBasicType[] | null,
            {
                loadAllTeams: async () => {
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. No generated function covers this endpoint yet. Find out why the generated client skips it (no schema, no product tag, or excluded from the spec) and fix that first.
                    return await api.loadPaginatedResults('api/projects')
                },
            },
        ],
        pendingAuth: [
            null as AgenticPendingAuth | null,
            {
                loadPendingAuth: async () => {
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. No generated function covers this endpoint yet. Find out why the generated client skips it (no schema, no product tag, or excluded from the spec) and fix that first.
                    return await api.get(`api/agentic/authorize/pending/?state=${encodeURIComponent(values.state)}`)
                },
            },
        ],
    })),
    reducers({
        state: [
            '' as string,
            {
                setState: (_, { state }) => state,
            },
        ],
        consentErrorCode: [
            null as string | null,
            {
                setConsentErrorCode: (_, { consentErrorCode }) => consentErrorCode,
            },
        ],
    }),
    forms(({ actions, values }) => ({
        agenticAuthorization: {
            defaults: {
                scoped_organizations: [],
                scoped_teams: [],
                access_type: 'teams',
            } as AgenticAuthorizationFormValues,
            // Selector-style errors so validation recomputes when the pending request resolves,
            // not only when form values change: a paying partner's form has no fields to fill.
            errors: [
                (s) => [s.agenticAuthorization, s.pendingAuth],
                (
                    { scoped_organizations, scoped_teams }: AgenticAuthorizationFormValues,
                    pendingAuth: AgenticPendingAuth | null
                ) =>
                    pendingAuth?.pays_for_customers
                        ? {}
                        : {
                              scoped_organizations: !scoped_organizations?.length
                                  ? ('Select an organization' as any)
                                  : undefined,
                              scoped_teams: !scoped_teams?.length ? ('Select a project' as any) : undefined,
                          },
            ],
            submit: async (formValues: AgenticAuthorizationFormValues) => {
                const controller = new AbortController()
                const timeoutId = window.setTimeout(() => controller.abort(), CONFIRM_TIMEOUT_MS)

                let response
                try {
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. No generated function covers this endpoint yet. Find out why the generated client skips it (no schema, no product tag, or excluded from the spec) and fix that first.
                    response = await api.create(
                        'api/agentic/authorize/confirm/',
                        {
                            state: values.state,
                            team_id: formValues.scoped_teams[0],
                            pays_for_customers: values.paysForCustomers,
                            partner_organization_id: values.pendingAuth?.partner_organization_id ?? null,
                        },
                        { signal: controller.signal }
                    )
                } catch (error) {
                    presentConfirmFailure(
                        describeConfirmFailure(error, values.partnerName),
                        actions.submitAgenticAuthorization
                    )
                    throw error
                } finally {
                    window.clearTimeout(timeoutId)
                }

                if (response?.redirect_url) {
                    window.location.href = response.redirect_url
                    return
                }

                // A 2xx with no redirect_url dead-ended the page silently; treat it as a failure.
                // An empty body (204, or a gateway answering 2xx with nothing) parses to a null
                // response, so read redirect_url optionally to route that through here too.
                presentConfirmFailure(
                    {
                        reason: 'missing_redirect_url',
                        message: 'Something went wrong while authorizing. Try again.',
                        retryable: true,
                    },
                    actions.submitAgenticAuthorization
                )
                throw new Error('Authorize confirm returned no redirect URL')
            },
        },
    })),
    listeners(() => ({
        cancel: () => {
            window.location.href = '/'
        },
    })),
    selectors(() => ({
        pageError: [
            (s) => [s.state, s.consentErrorCode],
            (state: string, consentErrorCode: string | null): ConsentError | null => {
                if (!state) {
                    return MISSING_STATE_ERROR
                }
                if (!consentErrorCode) {
                    return null
                }
                return Object.hasOwn(CONSENT_ERRORS, consentErrorCode)
                    ? CONSENT_ERRORS[consentErrorCode]
                    : UNKNOWN_CONSENT_ERROR
            },
        ],
        allOrganizations: [
            (s) => [s.user],
            (user: UserType): OrganizationBasicType[] => {
                return user?.organizations ?? []
            },
        ],
        filteredTeams: [
            (s) => [s.allTeams, s.agenticAuthorization],
            (allTeams: TeamBasicType[] | null, form: AgenticAuthorizationFormValues): TeamBasicType[] => {
                if (!allTeams) {
                    return []
                }
                const selectedOrgId = form.scoped_organizations[0]
                if (!selectedOrgId) {
                    return []
                }
                return allTeams.filter((team) => String(team.organization) === String(selectedOrgId) && !team.is_demo)
            },
        ],
        partnerName: [
            (s) => [s.pendingAuth],
            (pendingAuth: AgenticPendingAuth | null): string => {
                return pendingAuth?.partner_name ?? 'the requesting app'
            },
        ],
        paysForCustomers: [
            (s) => [s.pendingAuth],
            (pendingAuth: AgenticPendingAuth | null): boolean => pendingAuth?.pays_for_customers ?? false,
        ],
        partnerOrganizationName: [
            (s) => [s.pendingAuth],
            (pendingAuth: AgenticPendingAuth | null): string | null => pendingAuth?.partner_organization_name ?? null,
        ],
        scopes: [
            (s) => [s.pendingAuth],
            (pendingAuth: AgenticPendingAuth | null): string[] => {
                return pendingAuth?.scopes ?? []
            },
        ],
        scopeDescriptions: [
            (s) => [s.scopes],
            (scopes: string[]): string[] => {
                const minimumEquivalentScopes = getMinimumEquivalentScopes(scopes)
                return minimumEquivalentScopes.map(getScopeDescription).filter(Boolean) as string[]
            },
        ],
    })),
    urlToAction(({ actions }) => {
        const handleAuthorize = (_: Record<string, any>, searchParams: Record<string, any>): void => {
            if (searchParams['code']) {
                return
            }
            const state = (searchParams['state'] as string) ?? ''
            const consentErrorCode = searchParams['error'] ? String(searchParams['error']) : null

            actions.setState(state)
            actions.setConsentErrorCode(consentErrorCode)
            if (consentErrorCode) {
                return
            }
            if (state) {
                actions.loadPendingAuth()
            }
            actions.loadAllTeams()
        }

        return {
            '/agentic/authorize': handleAuthorize,
        }
    }),
])
