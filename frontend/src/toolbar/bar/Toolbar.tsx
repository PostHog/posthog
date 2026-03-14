import './Toolbar.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import {
    IconBolt,
    IconCursorClick,
    IconFlask,
    IconLive,
    IconPieChart,
    IconSearch,
    IconSpotlight,
    IconToggle,
    IconWarning,
} from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { AnimatedLogomark } from 'lib/brand/Logomark'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'

import { ActionsToolbarMenu } from '~/toolbar/actions/ActionsToolbarMenu'
import { MoreMenu } from '~/toolbar/bar/MoreMenu'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { UiHostConfigModal } from '~/toolbar/bar/UiHostConfigModal'
import { toolbarConfigLogic } from '~/toolbar/core/toolbarConfigLogic'
import { useToolbarFeatureFlag } from '~/toolbar/core/toolbarPosthogJS'
import { EventDebugMenu } from '~/toolbar/debug/EventDebugMenu'
import { HeatmapToolbarMenu } from '~/toolbar/elements/HeatmapToolbarMenu'
import { ExperimentsToolbarMenu } from '~/toolbar/experiments/ExperimentsToolbarMenu'
import { FlagsToolbarMenu } from '~/toolbar/flags/FlagsToolbarMenu'
import { productToursLogic } from '~/toolbar/product-tours/productToursLogic'
import { ProductToursSidebar } from '~/toolbar/product-tours/ProductToursSidebar'
import { ProductToursToolbarMenu } from '~/toolbar/product-tours/ProductToursToolbarMenu'
import { WebVitalsToolbarMenu } from '~/toolbar/web-vitals/WebVitalsToolbarMenu'

import { ToolbarButton } from './ToolbarButton'

export function ToolbarInfoMenu(): JSX.Element | null {
    const ref = useRef<HTMLDivElement | null>(null)
    const { visibleMenu, isDragging, menuProperties, minimized, isBlurred } = useValues(toolbarLogic)
    const { setMenu } = useActions(toolbarLogic)

    const { isAuthenticated } = useValues(toolbarConfigLogic)

    const showExperimentsFlag = useToolbarFeatureFlag('web-experiments')
    const showExperiments = inStorybook() || inStorybookTestRunner() || showExperimentsFlag

    const productToursFlag = useToolbarFeatureFlag('product-tours-2025')
    const showProductTours = inStorybook() || inStorybookTestRunner() || productToursFlag

    const content = minimized ? null : visibleMenu === 'flags' ? (
        <FlagsToolbarMenu />
    ) : visibleMenu === 'heatmap' ? (
        <HeatmapToolbarMenu />
    ) : visibleMenu === 'actions' ? (
        <ActionsToolbarMenu />
    ) : visibleMenu === 'debugger' ? (
        <EventDebugMenu />
    ) : visibleMenu === 'web-vitals' ? (
        <WebVitalsToolbarMenu />
    ) : visibleMenu === 'experiments' && showExperiments ? (
        <ExperimentsToolbarMenu />
    ) : visibleMenu === 'product-tours' && showProductTours ? (
        <ProductToursToolbarMenu />
    ) : null

    useEffect(() => {
        setMenu(ref.current)
        return () => setMenu(null)
    }, [ref.current]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (!isAuthenticated) {
        return null
    }

    return (
        <div
            className={clsx(
                'ToolbarMenu',
                !!content && 'ToolbarMenu--visible',
                isDragging && 'ToolbarMenu--dragging',
                isBlurred && 'ToolbarMenu--blurred',
                menuProperties.isBelow && 'ToolbarMenu--below'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: menuProperties.transform,
            }}
        >
            <div
                ref={ref}
                className="ToolbarMenu__content"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    maxHeight: menuProperties.maxHeight,
                }}
            >
                {content}
            </div>
        </div>
    )
}

export function Toolbar(): JSX.Element | null {
    const ref = useRef<HTMLDivElement | null>(null)
    const { minimized, position, isDragging, hedgehogMode, isEmbeddedInApp, isExiting, isLoading } =
        useValues(toolbarLogic)
    const { setVisibleMenu, toggleMinimized, onMouseOrTouchDown, setElement, setIsBlurred, completeGracefulExit } =
        useActions(toolbarLogic)
    const { isAuthenticated, userIntent, authStatus, uiHostConfigModalVisible } = useValues(toolbarConfigLogic)
    const { authenticate, openUiHostConfigModal, closeUiHostConfigModal } = useActions(toolbarConfigLogic)
    const { selectedTourId, isPreviewing } = useValues(productToursLogic)

    const showExperimentsFlag = useToolbarFeatureFlag('web-experiments')
    const showExperiments = inStorybook() || inStorybookTestRunner() || showExperimentsFlag

    const productToursFlag = useToolbarFeatureFlag('product-tours-2025')
    const showProductTours = inStorybook() || inStorybookTestRunner() || productToursFlag

    useEffect(() => {
        setElement(ref.current)
        return () => setElement(null)
    }, [ref.current]) // oxlint-disable-line react-hooks/exhaustive-deps

    useKeyboardHotkeys(
        {
            escape: { action: () => setVisibleMenu('none'), willHandleEvent: true },
        },
        []
    )

    useEffect(() => {
        if (userIntent === 'add-action' || userIntent === 'edit-action') {
            setVisibleMenu('actions')
        }

        if (userIntent === 'add-experiment' || userIntent === 'edit-experiment') {
            setVisibleMenu('experiments')
        }

        if (userIntent === 'heatmaps') {
            setVisibleMenu('heatmap')
        }

        if (userIntent === 'add-product-tour' || userIntent === 'edit-product-tour') {
            setVisibleMenu('product-tours')
        }
    }, [userIntent]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (isEmbeddedInApp) {
        return null
    }

    const showSidebar = selectedTourId !== null && !isPreviewing

    return (
        <>
            {showSidebar && <ProductToursSidebar />}
            <ToolbarInfoMenu />
            <div
                ref={ref}
                className={clsx('Toolbar', {
                    'Toolbar--minimized': minimized,
                    'Toolbar--hedgehog-mode': hedgehogMode,
                    'Toolbar--dragging': isDragging,
                    'Toolbar--extra-buttons-1': (showExperiments ? 1 : 0) + (showProductTours ? 1 : 0) === 1,
                    'Toolbar--extra-buttons-2': (showExperiments ? 1 : 0) + (showProductTours ? 1 : 0) === 2,
                })}
                onMouseDown={(e) => onMouseOrTouchDown(e.nativeEvent)}
                onTouchStart={(e) => onMouseOrTouchDown(e.nativeEvent)}
                onMouseOver={() => setIsBlurred(false)}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--toolbar-button-x': `${position.x}px`,
                        '--toolbar-button-y': `${position.y}px`,
                    } as any
                }
            >
                <ToolbarButton
                    onClick={isAuthenticated ? toggleMinimized : authenticate}
                    title={isAuthenticated ? 'Minimize' : 'Authenticate the PostHog Toolbar'}
                    titleMinimized={isAuthenticated ? 'Expand the toolbar' : 'Authenticate the PostHog Toolbar'}
                >
                    <AnimatedLogomark
                        animate={isLoading || authStatus === 'checking' || authStatus === 'authenticating'}
                        animateOnce={isExiting ? completeGracefulExit : undefined}
                        className="Toolbar__logomark"
                    />
                </ToolbarButton>
                {isAuthenticated ? (
                    <>
                        <ToolbarButton menuId="inspect">
                            <IconSearch />
                        </ToolbarButton>
                        <ToolbarButton menuId="heatmap">
                            <IconCursorClick />
                        </ToolbarButton>
                        <ToolbarButton menuId="actions">
                            <IconBolt />
                        </ToolbarButton>
                        <ToolbarButton menuId="flags" title="Feature flags">
                            <IconToggle />
                        </ToolbarButton>
                        <ToolbarButton menuId="debugger" title="Event debugger">
                            <IconLive />
                        </ToolbarButton>
                        <ToolbarButton menuId="web-vitals" title="Web vitals">
                            <IconPieChart />
                        </ToolbarButton>
                        {showExperiments && (
                            <ToolbarButton menuId="experiments" title="Experiments">
                                <IconFlask />
                            </ToolbarButton>
                        )}
                        {showProductTours && (
                            <ToolbarButton menuId="product-tours" title="Product tours">
                                <IconSpotlight />
                            </ToolbarButton>
                        )}
                    </>
                ) : authStatus === 'checking' || authStatus === 'authenticating' ? (
                    <ToolbarButton flex>
                        <span className="flex items-center gap-1">
                            <Spinner /> {authStatus === 'authenticating' ? 'Authenticating…' : 'Checking…'}
                        </span>
                    </ToolbarButton>
                ) : authStatus === 'error' ? (
                    <ToolbarButton
                        flex
                        onClick={openUiHostConfigModal}
                        title="PostHog app unreachable — click for help"
                    >
                        <span className="flex items-center gap-1">
                            Authenticate <IconWarning className="text-warning" />
                        </span>
                    </ToolbarButton>
                ) : (
                    <ToolbarButton flex onClick={authenticate}>
                        Authenticate
                    </ToolbarButton>
                )}
                <UiHostConfigModal visible={uiHostConfigModalVisible} onClose={closeUiHostConfigModal} />

                <MoreMenu />
            </div>
        </>
    )
}
