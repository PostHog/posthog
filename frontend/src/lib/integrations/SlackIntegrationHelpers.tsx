import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    LemonBanner,
    LemonBannerProps,
    LemonButton,
    LemonInputSelect,
    LemonInputSelectOption,
    Link,
    ProfilePicture,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { IconSlackExternal } from 'lib/lemon-ui/icons'

import { IntegrationType, SlackChannelType } from '~/types'

import type { SlackUserApi } from 'products/integrations/frontend/generated/api.schemas'

import { slackChannelId } from './slackChannel'
import { slackIntegrationLogic } from './slackIntegrationLogic'

export function SlackNotConfiguredBanner({
    type = 'info',
    className,
}: Partial<Pick<LemonBannerProps, 'type' | 'className'>>): JSX.Element {
    return (
        <LemonBanner type={type} className={className}>
            <div className="flex flex-col gap-2">
                <div className="flex justify-between gap-2 items-center">
                    <span>
                        Slack is not yet configured for this project. Add PostHog to your Slack workspace to continue.
                    </span>
                    <Link
                        to={api.integrations.authorizeUrl({
                            kind: 'slack',
                            next: window.location.pathname + '?target_type=slack',
                        })}
                        disableClientSideRouting
                    >
                        <img
                            alt="Add to Slack"
                            height="40"
                            width="139"
                            src="https://platform.slack-edge.com/img/add_to_slack.png"
                            srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                        />
                    </Link>
                </div>
                <span className="text-sm text-secondary">
                    Adding PostHog creates a public #posthog-inbox channel in your Slack workspace, where PostHog posts
                    what it finds.
                </span>
            </div>
        </LemonBanner>
    )
}

// Slack channel IDs are 9+ char uppercase alphanumerics beginning with C (public), G (private), or D (DM).
// Only trigger a direct lookup against Slack when the typed text plausibly *is* a channel ID, so
// free-text channel names route through the search endpoint instead.
const SLACK_CHANNEL_ID_PATTERN = /^[CGD][A-Z0-9]{8,}$/

const getSlackChannelOptions = (slackChannels?: SlackChannelType[] | null): LemonInputSelectOption[] | null => {
    return slackChannels
        ? slackChannels.map((x) => {
              const displayLabel = x.is_private_without_access
                  ? '🔒Private channel'
                  : `${x.is_private ? '🔒' : '#'}${x.name}`
              return {
                  key: `${x.id}|#${x.name}`,
                  labelComponent: (
                      <span className="flex items-center">
                          <span>{displayLabel}</span>
                          <span>{x.is_ext_shared ? <IconSlackExternal className="ml-2" /> : null}</span>
                      </span>
                  ),
                  label: displayLabel,
              }
          })
        : null
}

// A private channel the connecting user cannot see has no readable name, so keep it out of the list
// unless it is the current selection or the exact id being searched for.
const withoutInaccessiblePrivateChannels = (
    options: LemonInputSelectOption[] | null,
    isPrivateChannelWithoutAccess: (channelId: string) => boolean,
    visibleIds: (string | null | undefined)[]
): LemonInputSelectOption[] => {
    return (options ?? []).filter((option) => {
        const channelId = slackChannelId(option.key)
        return !isPrivateChannelWithoutAccess(channelId) || visibleIds.includes(channelId)
    })
}

// A saved channel beyond the loaded page has no option of its own, so add one labelled by name.
// Without it the picker renders the raw composite value.
const withSavedChannelOption = (
    options: LemonInputSelectOption[],
    savedValue: string | null | undefined
): LemonInputSelectOption[] => {
    if (!savedValue || options.some((option) => option.key === savedValue)) {
        return options
    }
    return [
        ...options,
        { key: savedValue, label: savedValue.includes('|') ? savedValue.split('|')[1] : 'Slack channel' },
    ]
}

const getSlackUserOptions = (slackUsers: SlackUserApi[]): LemonInputSelectOption[] => {
    return slackUsers.map((user) => {
        // Display names are not unique in a workspace, so surface the unique handle alongside
        // whenever it differs — otherwise two "@Alex" options are indistinguishable.
        const showHandle = Boolean(user.name) && user.name.toLowerCase() !== user.display_name.toLowerCase()
        return {
            key: `${user.id}|@${user.display_name}`,
            label: showHandle ? `@${user.display_name} (${user.name})` : `@${user.display_name}`,
            labelComponent: (
                <span className="flex items-center gap-1">
                    <span>@{user.display_name}</span>
                    {showHandle ? <span className="text-muted">({user.name})</span> : null}
                </span>
            ),
        }
    })
}

function SlackIntegrationInactiveBanner({ message }: { message: string }): JSX.Element {
    // Reconnecting overwrites the existing integration, which the API reserves for project admins
    // (`has_team_management_access`). Without this the banner would send a member through OAuth
    // only to have the write rejected at the end.
    const reconnectRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    return (
        <LemonBanner type="warning" className="mt-1">
            <div className="flex justify-between gap-2 items-center">
                <span>
                    {message}
                    {reconnectRestrictionReason ? ' Ask a project admin to reconnect it.' : ''}
                </span>
                {reconnectRestrictionReason ? null : (
                    <Link
                        to={api.integrations.authorizeUrl({
                            kind: 'slack',
                            next: window.location.pathname + '?target_type=slack',
                        })}
                        disableClientSideRouting
                    >
                        Reconnect Slack
                    </Link>
                )}
            </div>
        </LemonBanner>
    )
}

export type SlackUserPickerProps = {
    integration: IntegrationType
    /** Selected members in the `member_id|@display-name` composite format. */
    values?: string[]
    onChange?: (values: string[]) => void
    disabled?: boolean
    maxUsers?: number
}

export function SlackUserPicker({
    onChange,
    values,
    integration,
    disabled,
    maxUsers,
}: SlackUserPickerProps): JSX.Element {
    const logic = slackIntegrationLogic({ id: integration.id })
    const {
        slackUsers,
        allSlackUsers,
        allSlackUsersLoading,
        attemptedSlackUserIds,
        slackIntegrationInactiveMessage,
        getUsersRefreshButtonDisabledReason,
    } = useValues(logic)
    const { loadAllSlackUsers, loadSlackUserById } = useActions(logic)
    // Gates the empty-val recovery reload, mirroring SlackChannelPicker: LemonInputSelect clears its
    // input on blur/select, which must not re-trigger a full search round-trip every focus cycle.
    const hasActiveSearchRef = useRef(false)
    // The refresh action must keep the active query: LemonInputSelect filters options by the
    // visible text, so an unfiltered reload under it would hide a searched-for member.
    const activeSearchRef = useRef('')

    const usersRefreshButtonDisabledReason = getUsersRefreshButtonDisabledReason()
    // 1s tick while the cooldown is active so the countdown updates; otherwise idle the rerender.
    usePeriodicRerender(usersRefreshButtonDisabledReason ? 1000 : 60_000)

    useEffect(() => {
        // Read live logic values rather than the render closure: sibling pickers can mount within
        // the same commit, before the first one's dispatch is reflected in a re-render.
        // Gate on the directory itself, not on `slackUsers`: that pool also holds members resolved
        // by id, so a picker that resolved a saved recipient while disabled would otherwise count
        // as loaded and never fetch the list once it becomes editable.
        if (!disabled && !logic.values.allSlackUsers && !logic.values.allSlackUsersLoading) {
            loadAllSlackUsers()
        }
    }, [logic, loadAllSlackUsers, disabled])

    // Saved recipients absent from the loaded list (bare ids stored over the API, or members beyond
    // the first page) get a direct lookup so their chips render a name instead of a raw id. A
    // disabled picker (e.g. a disabled scout) never loads the directory, so its saved ids go
    // straight to lookup; an enabled one waits for the list, which usually resolves them for free.
    useEffect(() => {
        if (allSlackUsersLoading || (!disabled && !allSlackUsers)) {
            return
        }
        for (const value of values ?? []) {
            const memberId = value.split('|')[0]
            if (
                memberId &&
                !slackUsers.some((user: SlackUserApi) => user.id === memberId) &&
                !attemptedSlackUserIds[memberId]
            ) {
                loadSlackUserById(memberId)
            }
        }
    }, [values, slackUsers, allSlackUsers, allSlackUsersLoading, disabled, attemptedSlackUserIds, loadSlackUserById])

    // Re-key saved values onto the freshly listed member so a stale saved display name still matches
    // its option, keeping selection and options in sync by member id.
    const selectedValues = useMemo(
        () =>
            (values ?? []).map((value) => {
                const memberId = value.split('|')[0]
                const match = slackUsers.find((user: SlackUserApi) => user.id === memberId)
                return match ? `${match.id}|@${match.display_name}` : value
            }),
        [values, slackUsers]
    )

    const listedOptions = getSlackUserOptions(slackUsers)
    // Saved members missing from the current list (e.g. filtered out by an active search) still need
    // an option so their chips keep a readable label.
    const fallbackOptions = selectedValues
        .filter((value) => !listedOptions.some((option) => option.key === value))
        // A bare id keeps rendering as the id itself, which still identifies the recipient while
        // (or if) the direct lookup resolves a name for it.
        .map((value) => ({ key: value, label: value.includes('|') ? value.split('|')[1] : value }))
    const options = [...listedOptions, ...fallbackOptions]
    const atLimit = maxUsers !== undefined && selectedValues.length >= maxUsers

    return (
        <>
            <LemonInputSelect
                onChange={(vals) => onChange?.(vals)}
                onInputChange={(val) => {
                    if (val) {
                        loadAllSlackUsers(false, val)
                        hasActiveSearchRef.current = true
                        activeSearchRef.current = val
                    } else if (hasActiveSearchRef.current) {
                        loadAllSlackUsers()
                        hasActiveSearchRef.current = false
                        activeSearchRef.current = ''
                    }
                }}
                value={selectedValues}
                onFocus={() => !allSlackUsers && !allSlackUsersLoading && loadAllSlackUsers()}
                disabled={disabled}
                mode="multiple"
                data-attr="select-slack-users"
                placeholder={atLimit ? undefined : 'Select people...'}
                action={{
                    children: <span className="Link">Refresh members</span>,
                    onClick: () => loadAllSlackUsers(true, activeSearchRef.current),
                    // Also held while a load is in flight, so mashing the action can't stack
                    // concurrent full member enumerations against Slack.
                    disabledReason: allSlackUsersLoading ? 'Refreshing members…' : usersRefreshButtonDisabledReason,
                }}
                options={atLimit ? options.filter((option) => selectedValues.includes(option.key)) : options}
                loading={allSlackUsersLoading}
                emptyStateComponent={
                    <p className="text-secondary italic p-1 max-w-sm">
                        {atLimit
                            ? 'Recipient limit reached. Remove someone to add another person.'
                            : 'No members found.'}
                    </p>
                }
            />

            {slackIntegrationInactiveMessage ? (
                <SlackIntegrationInactiveBanner message={slackIntegrationInactiveMessage} />
            ) : null}

            {allSlackUsers?.has_more && !allSlackUsersLoading ? (
                <p className="text-secondary text-xs mt-1 mb-0">
                    Only the first page of members is shown. Type to search for a specific person.
                </p>
            ) : null}
        </>
    )
}

// Everything the picker reports about the current selection and the loaded list. Reads the same
// keyed logic as the picker rather than taking eight props for values it can select itself.
function SlackChannelPickerNotices({
    integration,
    value,
    showUnselectedSearchError,
}: {
    integration: IntegrationType
    value?: string
    showUnselectedSearchError: boolean
}): JSX.Element {
    const logic = slackIntegrationLogic({ id: integration.id })
    const {
        allSlackChannels,
        allSlackChannelsLoading,
        isMemberOfSlackChannel,
        isPrivateChannelWithoutAccess,
        getChannelRefreshButtonDisabledReason,
        slackIntegrationInactiveMessage,
    } = useValues(logic)
    const { loadAllSlackChannels } = useActions(logic)

    const showSlackMembershipWarning = value && isMemberOfSlackChannel(value) === false

    return (
        <>
            {showUnselectedSearchError ? (
                <p className="mt-1 mb-0 text-xs text-danger" role="alert">
                    No channel selected. Pick one from the list.
                </p>
            ) : null}

            {slackIntegrationInactiveMessage ? (
                <SlackIntegrationInactiveBanner message={slackIntegrationInactiveMessage} />
            ) : null}

            {allSlackChannels?.has_more && !allSlackChannelsLoading ? (
                <p className="text-secondary text-xs mt-1 mb-0">
                    Only the first page of channels is shown. Type to search for a specific channel.
                </p>
            ) : null}

            {showSlackMembershipWarning ? (
                <LemonBanner type="info">
                    <div className="flex gap-2 items-center">
                        <span>
                            The PostHog Slack App is not in this channel. Please add it to the channel otherwise
                            Subscriptions will fail to be delivered.{' '}
                            <Link to="https://posthog.com/docs/webhooks/slack" target="_blank">
                                See the Docs for more information
                            </Link>
                        </span>
                        <LemonButton
                            type="secondary"
                            disabledReason={getChannelRefreshButtonDisabledReason()}
                            onClick={() => loadAllSlackChannels(true)}
                            loading={allSlackChannelsLoading}
                        >
                            Check again
                        </LemonButton>
                    </div>
                </LemonBanner>
            ) : isPrivateChannelWithoutAccess(value ?? '') ? (
                <LemonBanner type="info">
                    This is a private Slack channel. Ask{' '}
                    <ProfilePicture user={integration.created_by} showName size="sm" /> or connect your own Slack
                    account to configure private channels.
                </LemonBanner>
            ) : null}
        </>
    )
}

export type SlackChannelPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
}

export function SlackChannelPicker({ onChange, value, integration, disabled }: SlackChannelPickerProps): JSX.Element {
    const logic = slackIntegrationLogic({ id: integration.id })
    const {
        slackChannels,
        slackChannelsForPicker,
        allSlackChannelsLoading,
        slackChannelByIdLoading,
        isPrivateChannelWithoutAccess,
        getChannelRefreshButtonDisabledReason,
    } = useValues(logic)
    const { loadAllSlackChannels, loadSlackChannelById, loadSlackChannelByIdSuccess } = useActions(logic)
    const [localValue, setLocalValue] = useState<string | null>(null)
    // Gates the empty-val recovery reload: LemonInputSelect's setInputValue('') on blur and
    // after-select would otherwise flicker the "first page of channels" hint on every focus cycle.
    const hasActiveSearchRef = useRef(false)
    // LemonInputSelect throws typed text away on blur, so someone who types a channel name and
    // clicks away is left with an empty input and no idea why. Track that case to show it back.
    const hasUnselectedSearchRef = useRef(false)
    const [blurredWithoutSelection, setBlurredWithoutSelection] = useState(false)
    // The marker and the state it feeds always clear together: a search that ended in a selection
    // was never dropped.
    const clearDroppedSearch = (): void => {
        hasUnselectedSearchRef.current = false
        setBlurredWithoutSelection(false)
    }
    // A pasted channel id is already an unambiguous choice, so hold it until the lookup resolves and
    // then pick it. Nobody should have to recognize their channel by id in the list.
    const [pastedChannelId, setPastedChannelId] = useState<string | null>(null)

    const channelRefreshButtonDisabledReason = getChannelRefreshButtonDisabledReason()
    // 1s tick while the cooldown is active so the countdown updates; otherwise idle the rerender (60s, picker is short-lived).
    usePeriodicRerender(channelRefreshButtonDisabledReason ? 1000 : 60_000)

    // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
    const rawSlackChannelOptions = useMemo(
        () => getSlackChannelOptions(slackChannelsForPicker),
        [slackChannelsForPicker]
    )

    const showUnselectedSearchError = blurredWithoutSelection && !value

    const modifiedValue = useMemo(() => {
        if (value?.split('|').length === 1) {
            const channel = slackChannels.find((x: SlackChannelType) => x.id === value)

            if (channel) {
                return `${channel.id}|#${channel.name}`
            }
        }

        return value
    }, [value, slackChannels])

    useEffect(() => {
        // Multiple pickers can mount for the same workspace (e.g. team + per-user channel), so skip
        // the fetch when the shared logic already has channels or a load in flight. Read live logic
        // values rather than the render closure: sibling pickers mount within the same commit, before
        // the first one's dispatch is reflected in a re-render.
        if (!disabled && !logic.values.slackChannels.length && !logic.values.allSlackChannelsLoading) {
            loadAllSlackChannels()
        }
    }, [logic, loadAllSlackChannels, disabled])

    useEffect(() => {
        // A caller can swap the integration (switching Slack workspace) without unmounting this
        // picker, so state from the old workspace's search must not leak into the new one.
        hasActiveSearchRef.current = false
        clearDroppedSearch()
        setLocalValue(null)
        setPastedChannelId(null)
    }, [integration.id])

    useEffect(() => {
        if (!pastedChannelId) {
            return
        }
        const channel = slackChannels.find((x: SlackChannelType) => x.id === pastedChannelId)
        if (!channel) {
            return
        }
        setPastedChannelId(null)
        clearDroppedSearch()
        if (slackChannelId(value ?? '') !== channel.id) {
            onChange?.(`${channel.id}|#${channel.name}`)
        }
    }, [pastedChannelId, slackChannels, value, onChange])

    // Read-only pickers still need a direct lookup because the saved channel may not be on the first page.
    useEffect(() => {
        if (value) {
            const channelId = value.split('|')[0]
            if (channelId) {
                loadSlackChannelById(channelId)
            }
        }
    }, [loadSlackChannelById, value])

    const options = withSavedChannelOption(
        withoutInaccessiblePrivateChannels(rawSlackChannelOptions, isPrivateChannelWithoutAccess, [value, localValue]),
        modifiedValue
    )

    return (
        <>
            <LemonInputSelect
                onChange={(val) => {
                    const key = val[0] ?? null
                    // LemonInputSelect blurs the input before it reports a selection, so onBlur has
                    // already flagged the search as dropped by the time this runs. Both happen on
                    // one synchronous call stack, so this reset wins and no error renders.
                    clearDroppedSearch()
                    if (key) {
                        // Pin into the by-id slot so the post-select bulk reload can't drop the
                        // channel from slackChannels and unresolve the label.
                        const [channelId] = key.split('|')
                        const channel = slackChannels.find((c: SlackChannelType) => c.id === channelId)
                        if (channel) {
                            loadSlackChannelByIdSuccess(channel)
                        }
                    }
                    onChange?.(key)
                }}
                onInputChange={(val) => {
                    if (val) {
                        // Slack channel IDs are uppercase; normalize so pasted lowercase IDs still
                        // resolve via direct lookup. ID-shape input fires only the direct lookup;
                        // anything else fires only the search, skipping the otherwise-redundant
                        // by-id call for a free-text channel name.
                        const idCandidate = val.trim().toUpperCase()
                        if (SLACK_CHANNEL_ID_PATTERN.test(idCandidate)) {
                            loadSlackChannelById(idCandidate)
                            setPastedChannelId(idCandidate)
                        } else if (val !== modifiedValue) {
                            setPastedChannelId(null)
                            // LemonInputSelect auto-fills the input with the selected option's key on
                            // focus (see LemonInputSelect._onFocus). Don't treat that auto-fill as a
                            // search — the composite "id|#name" matches no channel server-side and
                            // would overwrite the cached list with [], so the bare ID could no longer
                            // resolve to a name after blur.
                            loadAllSlackChannels(false, val)
                            hasActiveSearchRef.current = true
                        }
                        hasUnselectedSearchRef.current = true
                        setBlurredWithoutSelection(false)
                        setLocalValue(val)
                    } else if (hasActiveSearchRef.current) {
                        loadAllSlackChannels()
                        hasActiveSearchRef.current = false
                    }
                }}
                value={modifiedValue ? [modifiedValue] : []}
                onFocus={() => !slackChannels.length && !allSlackChannelsLoading && loadAllSlackChannels()}
                onBlur={() => setBlurredWithoutSelection(hasUnselectedSearchRef.current)}
                status={showUnselectedSearchError ? 'danger' : 'default'}
                disabled={disabled}
                mode="single"
                data-attr="select-slack-channel"
                placeholder="Select a channel..."
                action={{
                    children: <span className="Link">Refresh channels</span>,
                    onClick: () => loadAllSlackChannels(true),
                    disabledReason: channelRefreshButtonDisabledReason,
                }}
                emptyStateComponent={
                    // The popover is portaled outside the modal and matchWidth only sets min-width,
                    // not max-width — without a cap the popover can grow to fit a long single line
                    // and spill past the modal edge.
                    <p className="text-secondary italic p-1 max-w-sm">
                        No channels found. Make sure the PostHog Slack App is installed in the channel.{' '}
                        <Link to="https://posthog.com/docs/cdp/destinations/slack" target="_blank">
                            See the docs for more information.
                        </Link>
                    </p>
                }
                options={options}
                loading={allSlackChannelsLoading || slackChannelByIdLoading}
            />

            <SlackChannelPickerNotices
                integration={integration}
                value={value}
                showUnselectedSearchError={showUnselectedSearchError}
            />
        </>
    )
}
