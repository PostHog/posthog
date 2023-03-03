import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import type { flagPromptLogicType } from './flagPromptLogicType'

import posthog from 'posthog-js'
import { featureFlagLogic } from '../featureFlagLogic'
import { router } from 'kea-router'
import { PromptButtonType, PromptFlag, PromptPayload } from '~/types'

const DEBUG_IGNORE_LOCAL_STORAGE = false

const PROMPT_PREFIX = 'prompt-'

export function generateLocationCSS(location: string, cssSelector: string | undefined): Partial<CSSStyleDeclaration> {
    if (location === 'modal') {
        return {}
    }

    if (location.startsWith('relative-') && cssSelector) {
        const relativeLocation = location.split('-')[1]
        const relativeElement = findRelativeElement(cssSelector)
        const relativeElementRect = relativeElement.getBoundingClientRect()
        if (relativeLocation === 'top') {
            return {
                position: 'absolute',
                top: `${relativeElementRect.top - 10}px`,
                left: `${relativeElementRect.left + relativeElementRect.width / 2}px`,
                transform: 'translate(-50%, -100%)',
            }
        } else if (relativeLocation === 'bottom') {
            return {
                position: 'absolute',
                top: `${relativeElementRect.bottom + 10}px`,
                left: `${relativeElementRect.left + relativeElementRect.width / 2}px`,
                transform: 'translateX(-50%)',
            }
        } else if (relativeLocation === 'left') {
            return {
                position: 'absolute',
                top: `${relativeElementRect.top + relativeElementRect.height / 2}px`,
                left: `${relativeElementRect.left - 10}px`,
                transform: 'translate(-100%, -50%)',
            }
        } else if (relativeLocation === 'right') {
            return {
                position: 'absolute',
                top: `${relativeElementRect.top + relativeElementRect.height / 2}px`,
                left: `${relativeElementRect.right + 10}px`,
                transform: 'translateY(-50%)',
            }
        } else {
            throw new Error(`Unknown relative location: ${relativeLocation}`)
        }
    } else if (location === 'center') {
        return {
            position: 'fixed',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
        }
    } else if (location === 'bottom-right') {
        return {
            position: 'fixed',
            bottom: '10px',
            right: '10px',
        }
    } else if (location === 'bottom-left') {
        return {
            position: 'fixed',
            bottom: '10px',
            left: '10px',
        }
    } else if (location === 'top-right') {
        return {
            position: 'fixed',
            top: '10px',
            right: '10px',
        }
    } else if (location === 'top-left') {
        return {
            position: 'fixed',
            top: '10px',
            left: '10px',
        }
    } else {
        throw new Error(`Unknown location: ${location}`)
    }
}
export function generateTooltipPointerStyle(location: string): Partial<CSSStyleDeclaration> | undefined {
    if (location.startsWith('relative-')) {
        const relativeLocation = location.split('-')[1]
        if (relativeLocation === 'top') {
            return {
                position: 'absolute',
                top: '100%',
                left: '50%',
                transform: 'translateX(-50%)',
                borderLeft: '10px solid transparent',
                borderRight: '10px solid transparent',
                borderTop: '10px solid white',
            }
        } else if (relativeLocation === 'bottom') {
            return {
                position: 'absolute',
                bottom: '100%',
                left: '50%',
                transform: 'translateX(-50%)',
                borderLeft: '10px solid transparent',
                borderRight: '10px solid transparent',
                borderBottom: '10px solid white',
            }
        } else if (relativeLocation === 'left') {
            return {
                position: 'absolute',
                top: '50%',
                left: '100%',
                transform: 'translateY(-50%)',
                borderTop: '10px solid transparent',
                borderBottom: '10px solid transparent',
                borderLeft: '10px solid white',
            }
        } else if (relativeLocation === 'right') {
            return {
                position: 'absolute',
                top: '50%',
                right: '100%',
                transform: 'translateY(-50%)',
                borderTop: '10px solid transparent',
                borderBottom: '10px solid transparent',
                borderRight: '10px solid white',
            }
        } else {
            throw new Error(`Unknown relative location: ${relativeLocation}`)
        }
    }
}

function getFeatureSessionStorageKey(featureFlagName: string): string {
    return `ph-popup-${featureFlagName}`
}

function shouldShowPopup(featureFlagName: string): boolean {
    // The feature flag should have be disabled for the user once the popup has been shown
    // This is a second check for shorter-term preventing of the popup from showing
    const flagNotShownBefore = !localStorage.getItem(getFeatureSessionStorageKey(featureFlagName))

    return flagNotShownBefore || DEBUG_IGNORE_LOCAL_STORAGE
}

function sendPopupEvent(
    event: string,
    flag: string,
    payload: PromptPayload,
    buttonType: PromptButtonType | undefined = undefined
): void {
    if (buttonType) {
        posthog.capture(event, {
            popupFlag: flag,
            popupPayload: payload,
            popupButtonPressed: buttonType,
        })
    } else {
        posthog.capture(event, {
            flag: flag,
            payload: payload,
        })
    }
}

export function findRelativeElement(cssSelector: string): Element {
    const el = document.querySelector(cssSelector)
    if (!el) {
        throw new Error(`Could not find element with CSS selector: ${cssSelector}`)
    }
    return el
}

function updateTheOpenFlag(promptFlags: PromptFlag[], actions: any): void {
    for (const promptFlag of promptFlags) {
        // if there's no url to match against then default to showing the popup
        if (!promptFlag.payload.url_match || window.location.href.match(promptFlag.payload.url_match)) {
            if (shouldShowPopup(promptFlag.flag)) {
                actions.setOpenPromptFlag(promptFlag)
                return
            }
        }
    }
}

export const flagPromptLogic = kea<flagPromptLogicType>([
    path(['lib', 'logic', 'newPrompt']), // for some reason I couldn't add the flagPromptLogic to the path
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
                    return promptFlags.map((flag) => {
                        if (flag.flag === promptFlag.flag) {
                            return { ...flag, showingPrompt: true }
                        }
                        return flag
                    })
                },
                closePrompt: (promptFlags) => {
                    return promptFlags.map((flag) => {
                        return { ...flag, showingPrompt: false }
                    })
                },
                hidePrompt: (promptFlags, { promptFlag }) => {
                    return promptFlags.map((flag) => {
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
        // TODO: on url change, check if there's a popup to show
        setFeatureFlags: async ({ flags }, breakpoint) => {
            await breakpoint(100)
            const promptFlags: PromptFlag[] = []
            flags.forEach((flag: string) => {
                if (flag.startsWith(PROMPT_PREFIX) && posthog.isFeatureEnabled(flag)) {
                    const payload = posthog.getFeatureFlagPayload(flag) as PromptPayload
                    if (!payload || !payload.location) {
                        // indicates that it's not a valid popup
                        return
                    }
                    promptFlags.push({
                        flag,
                        payload,
                        showingPrompt: false,
                        locationCSS: generateLocationCSS(payload.location, payload.locationCSSSelector),
                        tooltipCSS: generateTooltipPointerStyle(payload.location),
                    })
                }
            })
            actions.setPromptFlags(promptFlags)
            updateTheOpenFlag(promptFlags, actions)
        },
        setOpenPromptFlag: async ({ promptFlag }, breakpoint) => {
            await breakpoint(1000)
            sendPopupEvent('popup shown', promptFlag.flag, promptFlag.payload)
        },
        closePrompt: async ({ promptFlag, buttonType }) => {
            if (promptFlag) {
                sendPopupEvent('popup closed', promptFlag, promptFlag.payload, buttonType)
                localStorage.setItem(getFeatureSessionStorageKey(promptFlag.flag), new Date().toDateString())
                posthog.people.set({ ['$' + promptFlag.flag]: new Date().toDateString() })

                if (promptFlag?.payload.primaryButtonURL && buttonType === 'primary') {
                    window.open(promptFlag.payload.primaryButtonURL, '_blank')
                }
            }
        },
        locationChanged: async ({}, breakpoint) => {
            await breakpoint(100)
            if (values.openPromptFlag && values.openPromptFlag.payload.url_match) {
                if (!window.location.href.match(values.openPromptFlag.payload.url_match)) {
                    actions.hidePrompt(values.openPromptFlag)
                }
            }

            updateTheOpenFlag(values.promptFlags, actions)
        },
    })),
    selectors({
        openPromptFlag: [
            (s) => [s.promptFlags],
            (promptFlags) => {
                return promptFlags.find((flag) => flag.showingPrompt)
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
