import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCamera, IconDay, IconLeave, IconNight, IconQuestion, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { IconFlare, IconMenu } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { ToolbarButton } from '~/toolbar/bar/ToolbarButton'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { postHogDebugInfoMenuItem, piiMaskingMenuItem } from '~/toolbar/bar/toolbarMenuItems'
import { toolbarConfigLogic } from '~/toolbar/core/toolbarConfigLogic'
import { useToolbarFeatureFlag } from '~/toolbar/core/toolbarPosthogJS'
import { screenshotUploadLogic } from '~/toolbar/screenshot-upload/screenshotUploadLogic'
import { ScreenshotUploadModal } from '~/toolbar/screenshot-upload/ScreenshotUploadModal'

const HELP_URL = 'https://posthog.com/docs/toolbar?utm_medium=in-product&utm_campaign=toolbar-help-button'

export function MoreMenu(): JSX.Element {
    const {
        hedgehogModeEnabled,
        hedgehogModeAvailable,
        theme,
        posthog,
        piiMaskingEnabled,
        piiMaskingColor,
        piiWarning,
    } = useValues(toolbarLogic)
    const {
        setHedgehogModeEnabled,
        toggleTheme,
        togglePiiMasking,
        setPiiMaskingColor,
        startGracefulExit,
        openHedgehogOptions,
    } = useActions(toolbarLogic)
    const { isAuthenticated } = useValues(toolbarConfigLogic)
    const { logout } = useActions(toolbarConfigLogic)
    const { isTakingScreenshot } = useValues(screenshotUploadLogic)
    const { takeScreenshot } = useActions(screenshotUploadLogic)

    const [loadingSurveys, setLoadingSurveys] = useState(true)
    const [surveysCount, setSurveysCount] = useState(0)

    useEffect(() => {
        posthog?.surveys?.getSurveys((surveys: any[]) => {
            setSurveysCount(surveys.length)
            setLoadingSurveys(false)
        }, false)
    }, [posthog])

    const showScreenshotForEvent = useToolbarFeatureFlag('event-media-previews')

    // KLUDGE: if there is no theme, assume light mode, which shouldn't be, but seems to be, necessary
    const currentlyLightMode = !theme || theme === 'light'

    return (
        <>
            <ScreenshotUploadModal />
            <LemonMenu
                placement="top-end"
                fallbackPlacements={['bottom-end']}
                items={
                    [
                        {
                            icon: <>🦔</>,
                            label: hedgehogModeEnabled ? 'Disable hedgehog mode' : 'Hedgehog mode',
                            disabledReason: !hedgehogModeAvailable
                                ? "Hedgehog mode is disabled. Hedgehog mode uses `new Function` directives to render WebGL, and that requires 'unsafe-eval' in your Content Security Policy's script-src directive"
                                : undefined,
                            onClick: () => {
                                setHedgehogModeEnabled(!hedgehogModeEnabled)
                            },
                        },
                        hedgehogModeEnabled && hedgehogModeAvailable
                            ? {
                                  icon: <IconFlare />,
                                  label: 'Hedgehog options',
                                  onClick: () => {
                                      openHedgehogOptions()
                                  },
                              }
                            : undefined,
                        {
                            icon: currentlyLightMode ? <IconNight /> : <IconDay />,
                            label: `Switch to ${currentlyLightMode ? 'dark' : 'light'} mode`,
                            onClick: () => toggleTheme(),
                        },
                        showScreenshotForEvent
                            ? {
                                  icon: <IconCamera />,
                                  label: 'Screenshot for event',
                                  onClick: takeScreenshot,
                                  disabled: isTakingScreenshot,
                              }
                            : undefined,
                        ...piiMaskingMenuItem(
                            piiMaskingEnabled,
                            piiMaskingColor,
                            togglePiiMasking,
                            setPiiMaskingColor,
                            piiWarning
                        ),
                        postHogDebugInfoMenuItem(posthog, loadingSurveys, surveysCount),
                        {
                            icon: <IconQuestion />,
                            label: 'Help',
                            onClick: () => {
                                window.open(HELP_URL, '_blank')?.focus()
                            },
                        },
                        isAuthenticated ? { icon: <IconLeave />, label: 'Sign out', onClick: logout } : undefined,
                        { icon: <IconX />, label: 'Close toolbar', onClick: startGracefulExit },
                    ].filter(Boolean) as LemonMenuItems
                }
                maxContentWidth={true}
            >
                <ToolbarButton>{isTakingScreenshot ? <Spinner /> : <IconMenu />}</ToolbarButton>
            </LemonMenu>
        </>
    )
}
