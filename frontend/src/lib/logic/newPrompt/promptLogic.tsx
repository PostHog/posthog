import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { PromptButtonType, PromptFlag, PromptPayload } from '~/types'

import { featureFlagLogic } from '../featureFlagLogic'
import type { promptLogicType } from './promptLogicType'

const PROMPT_PREFIX = 'prompt'
const LAST_SEEN = 'last-seen'
const MINIMUM_DAYS_BETWEEN_PROMPTS = 1

function getFeatureSessionStorageKey(featureFlagName: string): string {
    return `${PROMPT_PREFIX}-${featureFlagName}`
}

function getLastSeenSessionStorageKey(): string {
    return `${PROMPT_PREFIX}-${LAST_SEEN}`
}

function hasSeenPromptRecently(): boolean {
    const lastSeenPopup = localStorage.getItem(getLastSeenSessionStorageKey())
    const lastSeenPopupDate = lastSeenPopup ? new Date(lastSeenPopup) : null
    const oneDayAgo = new Date()
    oneDayAgo.setDate(oneDayAgo.getDate() - MINIMUM_DAYS_BETWEEN_PROMPTS)

    let seenRecently = false

    if (lastSeenPopupDate && lastSeenPopupDate > oneDayAgo) {
        seenRecently = true
    }
    return seenRecently
}

function shouldShowPopup(featureFlagName: string): boolean {
    // The feature flag should be disabled for the user once the prompt has been closed through the user properties
    // This is a second check for shorter-term preventing of the prompt from showing
    const flagShownBefore = localStorage.getItem(getFeatureSessionStorageKey(featureFlagName))

    const seenRecently = hasSeenPromptRecently()

    return !flagShownBefore && !seenRecently
}

function sendPopupEvent(
    event: string,
    promptFlag: PromptFlag,
    buttonType: PromptButtonType | undefined = undefined
): void {
    const properties = {
        flagName: promptFlag.flag,
        flagPayload: promptFlag.payload,
    }

    if (buttonType) {
        properties['buttonPressed'] = buttonType
    }

    posthog.capture(event, properties)
}

export const promptLogic = kea<promptLogicType>([
    path(['lib', 'logic', 'newPrompt', 'promptLogic']),
    actions({
        closePrompt: (promptFlag: PromptFlag, buttonType: PromptButtonType) => ({ promptFlag, buttonType }),
        setPromptFlags: (promptFlags: PromptFlag[]) => ({ promptFlags }),
        searchForValidFlags: true,
        setOpenPromptFlag: (promptFlag: PromptFlag) => ({ promptFlag }),
        // hide the prompt without sending an event or setting the localstorage
        // used for when the user navigates away from the page
        hidePromptWithoutSaving: (promptFlag: PromptFlag) => ({ promptFlag }),
    }),
    connect({
        actions: [featureFlagLogic, ['setFeatureFlags'], router, ['locationChanged']],
    }),
    reducers({
        promptFlags: [
            [] as PromptFlag[],
            {
                setPromptFlags: (_, { promptFlags }) => promptFlags,
                setOpenPromptFlag: (promptFlags, { promptFlag }) => {
                    return promptFlags.map((flag: PromptFlag) => {
                        if (flag.flag === promptFlag.flag) {
                            return { ...flag, showingPrompt: true }
                        }
                        return flag
                    })
                },
                closePrompt: (promptFlags) => {
                    return promptFlags.map((flag: PromptFlag) => {
                        return { ...flag, showingPrompt: false }
                    })
                },
                hidePromptWithoutSaving: (promptFlags, { promptFlag }) => {
                    return promptFlags.map((flag: PromptFlag) => {
                        if (flag.flag === promptFlag.flag) {
                            return { ...flag, showingPrompt: false }
                        }
                        return flag
                    })
                },
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        // TODO: on url change, check if there's a prompt to show
        setFeatureFlags: async ({ flags }, breakpoint) => {
            await breakpoint(100)
            const promptFlags: PromptFlag[] = []
            flags.forEach((flag: string) => {
                if (flag.startsWith(PROMPT_PREFIX) && posthog.isFeatureEnabled(flag)) {
                    const payload = posthog.getFeatureFlagPayload(flag) as PromptPayload
                    if (!payload || !payload.type) {
                        // indicates that it's not a valid prompt
                        return
                    }
                    promptFlags.push({
                        flag,
                        payload,
                        showingPrompt: false,
                    })
                }
            })
            actions.setPromptFlags(promptFlags)
            actions.searchForValidFlags()
        },
        searchForValidFlags: async () => {
            for (const promptFlag of values.promptFlags) {
                if (!promptFlag.payload.url_match || window.location.href.match(promptFlag.payload.url_match)) {
                    if (shouldShowPopup(promptFlag.flag)) {
                        actions.setOpenPromptFlag(promptFlag)
                        return // only show one prompt at a time
                    }
                }
            }
        },
        setOpenPromptFlag: async ({ promptFlag }, breakpoint) => {
            await breakpoint(1000)
            sendPopupEvent('Prompt shown', promptFlag)
        },
        closePrompt: async ({ promptFlag, buttonType }) => {
            if (promptFlag) {
                sendPopupEvent('Prompt closed', promptFlag, buttonType)
                localStorage.setItem(getFeatureSessionStorageKey(promptFlag.flag), new Date().toDateString())
                localStorage.setItem(getLastSeenSessionStorageKey(), new Date().toDateString())
                posthog.people.set({ ['$' + promptFlag.flag]: new Date().toDateString() })

                if (promptFlag?.payload.primaryButtonURL && buttonType === 'primary') {
                    window.open(promptFlag.payload.primaryButtonURL, '_blank')
                }
            }
        },
        locationChanged: async (_, breakpoint) => {
            await breakpoint(100)
            if (values.openPromptFlag && values.openPromptFlag.payload.url_match) {
                if (!window.location.href.match(values.openPromptFlag.payload.url_match)) {
                    actions.hidePromptWithoutSaving(values.openPromptFlag)
                }
            }

            actions.searchForValidFlags()
        },
    })),
    selectors({
        openPromptFlag: [
            (s) => [s.promptFlags],
            (promptFlags) => {
                return promptFlags.find((flag: PromptFlag) => flag.showingPrompt)
            },
        ],
        payload: [
            (s) => [s.openPromptFlag],
            (openPromptFlag: PromptFlag) => {
                return openPromptFlag?.payload
            },
        ],
    }),
])
