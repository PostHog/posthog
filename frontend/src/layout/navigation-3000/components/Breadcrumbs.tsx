import React, { useLayoutEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { IconArrowDropDown } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import './Breadcrumbs.scss'
import { FinalizedBreadcrumb } from '~/types'
import clsx from 'clsx'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { EditableField } from 'lib/components/EditableField/EditableField'

const COMPACTION_DISTANCE = 44

/**
 * In PostHog 3000 breadcrumbs also serve as the top bar. This is marked by theses two features:
 * - The "More scene actions" button (vertical ellipsis)
 * - The "Quick scene actions" buttons (zero or more buttons on the right)
 */
export function Breadcrumbs(): JSX.Element | null {
    const { breadcrumbs, renameState } = useValues(breadcrumbsLogic)
    const { setActionsContainer } = useActions(breadcrumbsLogic)

    const [compactionRate, setCompactionRate] = useState(0)

    useLayoutEffect(() => {
        function handleScroll(): void {
            const scrollTop = document.getElementsByTagName('main')[0].scrollTop
            const newCompactionRate = Math.min(scrollTop / COMPACTION_DISTANCE, 1)
            setCompactionRate(newCompactionRate)
            if (
                renameState &&
                ((newCompactionRate > 0.5 && compactionRate <= 0.5) ||
                    (newCompactionRate <= 0.5 && compactionRate > 0.5))
            ) {
                // Transfer selection from the outgoing input to the incoming one
                const [source, target] = newCompactionRate > 0.5 ? ['large', 'small'] : ['small', 'large']
                const sourceEl = document.querySelector<HTMLInputElement>(`input[name="item-name-${source}"]`)
                const targetEl = document.querySelector<HTMLInputElement>(`input[name="item-name-${target}"]`)
                if (sourceEl && targetEl) {
                    targetEl.focus()
                    targetEl.setSelectionRange(sourceEl.selectionStart || 0, sourceEl.selectionEnd || 0)
                }
            }
        }
        const main = document.getElementsByTagName('main')[0]
        main.addEventListener('scroll', handleScroll)
        return () => main.removeEventListener('scroll', handleScroll)
    }, [compactionRate])

    return breadcrumbs.length ? (
        <div
            className="Breadcrumbs3000"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--breadcrumbs-compaction-rate': compactionRate,
                    // It wouldn't be necessary to set visibility, but for some reason without this positioning
                    // of breadcrumbs becomes borked when entering title editing mode
                    '--breadcrumbs-title-large-visibility': compactionRate === 1 ? 'hidden' : 'visible',
                    '--breadcrumbs-title-small-visibility': compactionRate === 0 ? 'hidden' : 'visible',
                } as React.CSSProperties
            }
        >
            <div className="Breadcrumbs3000__content">
                <div className="Breadcrumbs3000__trail">
                    <div className="Breadcrumbs3000__crumbs">
                        {breadcrumbs.slice(0, -1).map((breadcrumb, index) => (
                            <React.Fragment key={breadcrumb.name || '…'}>
                                <Breadcrumb breadcrumb={breadcrumb} index={index} />
                                <div className="Breadcrumbs3000__separator" />
                            </React.Fragment>
                        ))}
                        <Breadcrumb
                            breadcrumb={breadcrumbs[breadcrumbs.length - 1]}
                            index={breadcrumbs.length - 1}
                            here
                        />
                    </div>
                    <Here breadcrumb={breadcrumbs[breadcrumbs.length - 1]} />
                </div>
                <div className="Breadcrumbs3000__actions" ref={setActionsContainer} />
            </div>
        </div>
    ) : null
}

interface BreadcrumbProps {
    breadcrumb: FinalizedBreadcrumb
    index: number
    here?: boolean
}

function Breadcrumb({ breadcrumb, index, here }: BreadcrumbProps): JSX.Element {
    const { renameState } = useValues(breadcrumbsLogic)
    const { tentativelyRename, finishRenaming } = useActions(breadcrumbsLogic)
    const [popoverShown, setPopoverShown] = useState(false)

    let nameElement: JSX.Element
    if (breadcrumb.name != null && breadcrumb.onRename) {
        nameElement = (
            <EditableField
                name="item-name-small"
                value={renameState && renameState[0] === breadcrumb.globalKey ? renameState[1] : breadcrumb.name}
                onChange={(newName) => tentativelyRename(breadcrumb.globalKey, newName)}
                onSave={(newName) => {
                    void breadcrumb.onRename?.(newName)
                }}
                mode={renameState && renameState[0] === breadcrumb.globalKey ? 'edit' : 'view'}
                onModeToggle={(newMode) => {
                    if (newMode === 'edit') {
                        tentativelyRename(breadcrumb.globalKey, breadcrumb.name as string)
                    } else {
                        finishRenaming()
                    }
                    setPopoverShown(false)
                }}
                compactButtons="xsmall"
                editingIndication="underlined"
            />
        )
    } else {
        nameElement = <span>{breadcrumb.name}</span>
    }

    const Component = breadcrumb.path ? Link : 'div'
    const breadcrumbContent = (
        <Component
            className={clsx(
                'Breadcrumbs3000__breadcrumb',
                popoverShown && 'Breadcrumbs3000__breadcrumb--open',
                (breadcrumb.path || breadcrumb.popover) && 'Breadcrumbs3000__breadcrumb--actionable',
                here && 'Breadcrumbs3000__breadcrumb--here'
            )}
            onClick={() => {
                breadcrumb.popover && setPopoverShown(!popoverShown)
            }}
            data-attr={`breadcrumb-${index}`}
            to={breadcrumb.path}
        >
            {nameElement}
            {breadcrumb.popover && <IconArrowDropDown />}
        </Component>
    )

    if (breadcrumb.popover) {
        return (
            <Popover
                {...breadcrumb.popover}
                visible={popoverShown}
                onClickOutside={() => {
                    if (popoverShown) {
                        setPopoverShown(false)
                    }
                }}
                onClickInside={() => {
                    if (popoverShown) {
                        setPopoverShown(false)
                    }
                }}
            >
                {breadcrumbContent}
            </Popover>
        )
    }

    return breadcrumbContent
}

interface HereProps {
    breadcrumb: FinalizedBreadcrumb
}

function Here({ breadcrumb }: HereProps): JSX.Element {
    const { renameState } = useValues(breadcrumbsLogic)
    const { tentativelyRename, finishRenaming } = useActions(breadcrumbsLogic)

    return (
        <h1 className="Breadcrumbs3000__here">
            {breadcrumb.name == null ? (
                <LemonSkeleton className="w-40 h-4" />
            ) : breadcrumb.onRename ? (
                <EditableField
                    name="item-name-large"
                    value={renameState && renameState[0] === breadcrumb.globalKey ? renameState[1] : breadcrumb.name}
                    onChange={(newName) => tentativelyRename(breadcrumb.globalKey, newName)}
                    onSave={(newName) => {
                        void breadcrumb.onRename?.(newName)
                    }}
                    mode={renameState && renameState[0] === breadcrumb.globalKey ? 'edit' : 'view'}
                    onModeToggle={(newMode) => {
                        if (newMode === 'edit') {
                            tentativelyRename(breadcrumb.globalKey, breadcrumb.name as string)
                        } else {
                            finishRenaming()
                        }
                    }}
                    compactButtons="xsmall"
                    editingIndication="underlined"
                />
            ) : (
                <span>{breadcrumb.name}</span>
            )}
        </h1>
    )
}
