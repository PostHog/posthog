import { useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'
import { HomepageInput } from './HomepageInput'
import { HomepageSearchResults } from './HomepageSearchResults'
import { HomepageThread } from './HomepageThread'

const PHASE_ORDER = ['idle', 'moving', 'separator', 'content'] as const

function phaseAtLeast(current: string, target: string): boolean {
    return PHASE_ORDER.indexOf(current as any) >= PHASE_ORDER.indexOf(target as any)
}

export function AiFirstHomepage(): JSX.Element {
    const { mode, animationPhase } = useValues(aiFirstHomepageLogic)

    return (
        <div className="flex flex-col grow overflow-hidden h-full">
            {/* Top spacer */}
            <div
                className={cn(
                    'transition-[flex-grow] duration-300 ease-out motion-reduce:duration-0',
                    mode === 'search' ? 'grow-0' : 'grow'
                )}
            />

            {/* AI thread (above input, visible in ai mode) */}
            {mode === 'ai' && animationPhase === 'content' && (
                <div className="animate-fade-in overflow-y-auto grow">
                    <HomepageThread />
                </div>
            )}

            {/* Top separator */}
            {mode !== 'idle' && (
                <div
                    className={cn(
                        'border-b transition-opacity duration-200 motion-reduce:duration-0',
                        phaseAtLeast(animationPhase, 'separator') ? 'opacity-100' : 'opacity-0'
                    )}
                />
            )}

            {/* Input - always rendered */}
            <HomepageInput />

            {/* Bottom separator */}
            {mode !== 'idle' && (
                <div
                    className={cn(
                        'border-b transition-opacity duration-200 motion-reduce:duration-0',
                        phaseAtLeast(animationPhase, 'separator') ? 'opacity-100' : 'opacity-0'
                    )}
                />
            )}

            {/* Search results (below input, visible in search mode) */}
            {mode === 'search' && animationPhase === 'content' && (
                <div className="animate-fade-in overflow-y-auto grow">
                    <HomepageSearchResults />
                </div>
            )}

            {/* Bottom spacer */}
            <div
                className={cn(
                    'transition-[flex-grow] duration-300 ease-out motion-reduce:duration-0',
                    mode === 'ai' ? 'grow-0' : 'grow'
                )}
            />
        </div>
    )
}
