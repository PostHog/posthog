import type React from 'react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import type { HogChartTheme, TooltipConfig, TooltipContext } from '../../types'
import { DefaultTooltip } from './DefaultTooltip'
import { TooltipPositioner } from './TooltipPositioner'

interface TooltipPortalProps {
    context: TooltipContext | null
    config?: TooltipConfig
    theme?: Partial<HogChartTheme>
    containerRef: React.RefObject<HTMLElement>
}

export function TooltipPortal({ context, config, theme, containerRef }: TooltipPortalProps): JSX.Element | null {
    const [portalEl, setPortalEl] = useState<HTMLDivElement | null>(null)

    useEffect(() => {
        const el = document.createElement('div')
        el.className = 'hog-charts-tooltip-portal'
        el.setAttribute('data-attr', 'hog-charts-tooltip')
        document.body.appendChild(el)
        setPortalEl(el)
        return () => {
            el.remove()
        }
    }, [])

    useEffect(() => {
        if (!portalEl) {
            return
        }
        if (context) {
            portalEl.style.opacity = '1'
            portalEl.style.pointerEvents = 'none'
        } else {
            portalEl.style.opacity = '0'
            portalEl.style.pointerEvents = 'none'
            config?.onHide?.()
        }
    }, [context, config, portalEl])

    if (!context || !portalEl) {
        return null
    }

    const content = config?.render ? (
        config.render(context)
    ) : (
        <DefaultTooltip context={context} theme={theme} formatValueFn={config?.formatValue} />
    )

    return createPortal(
        <TooltipPositioner context={context} containerRef={containerRef}>
            {content}
        </TooltipPositioner>,
        portalEl
    )
}
