import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import posthog from 'posthog-js'
import { featureFlagLogic } from '../featureFlagLogic'
import { router } from 'kea-router'
import { PromptButtonType, PromptFlag, PromptPayload } from '~/types'

import type { promptLogicType } from './promptLogicType'

const PROMPT_PREFIX = 'ph-prompt'
const LAST_SEEN = 'last-seen'
const MINIMUM_DAYS_BETWEEN_PROMPTS = 1

function getFeatureSessionStorageKey(featureFlagName: string): string {
    return `${PROMPT_PREFIX}-${featureFlagName}`
}

function getLastSeenSessionStorageKey(): string {
    return `${PROMPT_PREFIX}-${LAST_SEEN}`
}

function hasSeenPromptRecently(): boolean {
    const lastSeenPoup = localStorage.getItem(getLastSeenSessionStorageKey())
    const lastSeenPoupDate = lastSeenPoup ? new Date(lastSeenPoup) : null
    const now = new Date()
    const oneDayAgo = new Date(now)
    oneDayAgo.setDate(now.getDate() - MINIMUM_DAYS_BETWEEN_PROMPTS)

    let seenRecently = false

    if (lastSeenPoupDate && lastSeenPoupDate > oneDayAgo) {
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

function setTheOpenFlag(promptFlags: PromptFlag[], actions: any): void {
    for (const promptFlag of promptFlags) {
        if (!promptFlag.payload.url_match || window.location.href.match(promptFlag.payload.url_match)) {
            if (shouldShowPopup(promptFlag.flag)) {
                actions.setOpenPromptFlag(promptFlag)
                return // only show one prompt at a time
            }
        }
    }
}

export const promptLogic = kea<promptLogicType>([
    path(['lib', 'logic', 'newPrompt']), // for some reason I couldn't add the promptLogic to the path
    actions({
        closePrompt: (promptFlag: PromptFlag, buttonType: PromptButtonType) => ({ promptFlag, buttonType }),
        setPromptFlags: (promptFlags: PromptFlag[]) => ({ promptFlags }),
        setOpenPromptFlag: (promptFlag: PromptFlag) => ({ promptFlag }),
        // hide the prompt without sending an event or setting the localstorage
        // used for when the user navigates away from the page
        hidePrompt: (promptFlag: PromptFlag) => ({ promptFlag }),
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
                hidePrompt: (promptFlags, { promptFlag }) => {
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
            setTheOpenFlag(promptFlags, actions)
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
                    actions.hidePrompt(values.openPromptFlag)
                }
            }

            setTheOpenFlag(values.promptFlags, actions)
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
