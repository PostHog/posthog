import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import type { flagPromptLogicType } from './flagPromptLogicType'

import posthog from 'posthog-js'
import { featureFlagLogic } from '../featureFlagLogic'

const DEBUG_IGNORE_LOCAL_STORAGE = false

const PROMPT_PREFIX = 'prompt-'

type PromptButtonType = 'primary' | 'secondary'

type PromptPayload = {
    title: string
    body: string
    primaryButtonText: string
    secondaryButtonText: string
    location: string
    primaryButtonURL: string
    url_match: string
    locationCSSSelector: string
}

type PromptFlag = {
    flag: string
    payload: PromptPayload
    showingPrompt: boolean
    locationCSS: Partial<CSSStyleDeclaration>
    tooltipCSS?: Partial<CSSStyleDeclaration>
}

export function generateLocationCSS(location: string, cssSelector: string): Partial<CSSStyleDeclaration> {
    if (location.startsWith('relative-')) {
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
    } else if (location === 'absolute-center') {
        return {
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
        }
    } else if (location === 'absolute-bottom-right') {
        return {
            position: 'absolute',
            bottom: '10px',
            right: '10px',
        }
    } else if (location === 'absolute-bottom-left') {
        return {
            position: 'absolute',
            bottom: '10px',
            left: '10px',
        }
    } else if (location === 'absolute-top-right') {
        return {
            position: 'absolute',
            top: '10px',
            right: '10px',
        }
    } else if (location === 'absolute-top-left') {
        return {
            position: 'absolute',
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
                actions.setOpenPromptFlag(promptFlag.flag)
                console.log('setting active flag', promptFlag.flag)
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
        setOpenPromptFlag: (toOpenFlag: string) => ({ toOpenFlag }),
    }),
    connect({
        actions: [featureFlagLogic, ['setFeatureFlags']],
    }),
    reducers({
        promptFlags: [
            [] as PromptFlag[],
            {
                setPromptFlags: (_, { promptFlags }) => promptFlags,
                setOpenPromptFlag: (promptFlags, { toOpenFlag }) => {
                    return promptFlags.map((flag) => {
                        if (flag.flag === toOpenFlag) {
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
            console.log('prompt flags', promptFlags, flags)
            updateTheOpenFlag(promptFlags, actions)
        },
        setOpenPromptFlag: async ({ toOpenFlag }, breakpoint) => {
            await breakpoint(1000)
            sendPopupEvent('popup shown', toOpenFlag, values.payload)
        },
        closePrompt: async ({ promptFlag, buttonType }) => {
            if (promptFlag) {
                sendPopupEvent('popup closed', promptFlag, values.payload, buttonType)
                localStorage.setItem(getFeatureSessionStorageKey(promptFlag.flag), new Date().toDateString())
                posthog.people.set({ ['$' + promptFlag.flag]: new Date().toDateString() })

                if (promptFlag?.payload.primaryButtonURL && buttonType === 'primary') {
                    window.open(promptFlag.payload.primaryButtonURL, '_blank')
                }
            }
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
