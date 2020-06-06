import './ToolbarButton.scss'

import React, { useState, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { useLongPress } from 'lib/hooks/useLongPress'
import { CloseOutlined, ProfileOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'
import { Logo } from '~/toolbar/assets/Logo'

export function ToolbarButton({ dockLogic, shadowRef }) {
    const { dock, float, hideButton } = useActions(dockLogic)
    const { nextOpenMode } = useValues(dockLogic)

    const [buttonsExtended, setButtonsExtended] = useState('')
    const timeoutRef = useRef(null)

    function extendButtons(x, y) {
        window.clearTimeout(timeoutRef.current)
        const ns = y < window.innerHeight / 2 ? 's' : 'n'
        const we = x < window.innerWidth / 2 ? 'e' : 'w'
        if (buttonsExtended !== `${ns}${we}`) {
            setButtonsExtended(`${ns}${we}`)
        }
    }

    function onMouseMove() {
        if (shadowRef.current) {
            const element = shadowRef.current.shadowRoot.getElementById('button-toolbar')
            if (element) {
                const rect = element.getBoundingClientRect()
                extendButtons(rect.x + rect.width / 2, rect.y + rect.height / 2)
            }
        }
    }

    function onMouseLeave() {
        timeoutRef.current = window.setTimeout(() => setButtonsExtended(''), 400)
    }

    const longPressEvents = useLongPress(
        (clicked, _ms, coords) => {
            if (clicked) {
                nextOpenMode === 'float' ? float() : dock()
            } else {
                extendButtons(coords[0], coords[1])
            }
        },
        { ms: 700, clickMs: 1 }
    )

    return (
        <>
            <div
                className="floating-toolbar-button"
                {...longPressEvents}
                onMouseMove={e => {
                    onMouseMove(e)
                    longPressEvents.onMouseMove(e)
                }}
                onMouseLeave={e => {
                    onMouseLeave(e)
                    longPressEvents.onMouseLeave(e)
                }}
            >
                <Logo />
            </div>

            <div
                className={`floating-tiny-button float-button${
                    buttonsExtended ? ` extended extended-${buttonsExtended}` : ''
                }`}
                onMouseMove={onMouseMove}
                onMouseLeave={onMouseLeave}
            >
                <div className="float-content" onClick={float}>
                    <Tooltip
                        title="Floating Toolbar"
                        placement={buttonsExtended.includes('e') ? 'right' : 'left'}
                        getPopupContainer={() => shadowRef.current.shadowRoot}
                    >
                        <ProfileOutlined />
                    </Tooltip>
                </div>
            </div>
            <div
                className={`floating-tiny-button close-button${
                    buttonsExtended ? ` extended extended-${buttonsExtended}` : ''
                }`}
                onMouseMove={onMouseMove}
                onMouseLeave={onMouseLeave}
            >
                <div className="float-content" onClick={hideButton}>
                    <Tooltip
                        title="Hide"
                        placement={buttonsExtended.includes('e') ? 'right' : 'left'}
                        getPopupContainer={() => shadowRef.current.shadowRoot}
                    >
                        <CloseOutlined />
                    </Tooltip>
                </div>
            </div>
        </>
    )
}
