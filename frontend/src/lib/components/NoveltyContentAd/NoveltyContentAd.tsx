import './NoveltyContentAd.scss'

import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { noveltyContentAdLogic } from './noveltyContentAdLogic'

export function NoveltyContentAd(): JSX.Element | null {
    const { currentAd, isDismissed } = useValues(noveltyContentAdLogic)
    const { dismissAd } = useActions(noveltyContentAdLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    if (isDismissed || isLayoutNavCollapsed) {
        return null
    }

    return (
        <div className="NoveltyContentAd w-full">
            <div className="relative bg-gradient-to-br from-purple-600/10 via-pink-500/10 to-orange-500/10 border border-purple-500/20 rounded-lg p-3 overflow-hidden">
                <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAiIGhlaWdodD0iMjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGRlZnM+PHBhdHRlcm4gaWQ9ImdyaWQiIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgcGF0dGVyblVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PHBhdGggZD0iTSAwIDAgTCAyMCAwIDIwIDIwIDAgMjAgMCAwIiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utb3BhY2l0eT0iMC4wNSIgc3Ryb2tlLXdpZHRoPSIxIi8+PC9wYXR0ZXJuPjwvZGVmcz48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSJ1cmwoI2dyaWQpIi8+PC9zdmc+')] opacity-30" />

                <div className="relative z-10">
                    <div className="flex items-start justify-between mb-2">
                        <div className="flex items-center gap-1.5">
                            <span className="text-lg">💎</span>
                            <span className="text-xs font-semibold text-purple-600 dark:text-purple-400 uppercase tracking-wide">
                                Sponsored
                            </span>
                        </div>
                        <LemonButton
                            icon={<IconX className="text-muted" />}
                            tooltip="Dismiss"
                            tooltipPlacement="right"
                            size="xxsmall"
                            onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                dismissAd()
                            }}
                            noPadding
                            className="shrink-0"
                        />
                    </div>

                    <div className="space-y-2">
                        <h3 className="text-sm font-bold leading-tight m-0">{currentAd.title}</h3>
                        <p className="text-xs text-muted m-0 leading-relaxed">{currentAd.description}</p>

                        <div className="flex items-center justify-between pt-1">
                            <span className="text-sm font-bold text-green-600 dark:text-green-400">
                                {currentAd.price}
                            </span>
                            <button className="px-3 py-1 text-xs font-medium bg-gradient-to-r from-purple-600 to-pink-600 text-white rounded-md hover:from-purple-700 hover:to-pink-700 transition-all duration-200 shadow-sm hover:shadow-md">
                                {currentAd.cta}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
