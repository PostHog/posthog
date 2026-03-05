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

    const isIdle = mode === 'idle'
    const isAi = mode === 'ai'
    const isSearch = mode === 'search'
    const isContent = animationPhase === 'content'

    return (
        <div className="flex flex-col grow overflow-hidden h-full">
            {/* Top spacer — grows in idle (centering) and AI pre-content (pushes input to bottom) */}
            <div
                className={cn(
                    'basis-0 transition-[flex-grow] duration-300 ease-out motion-reduce:duration-0',
                    isIdle || (isAi && !isContent) ? 'grow' : 'grow-0'
                )}
            />

            {/* Thread container — always present, grows via flex when AI content phase */}
            <div
                className={cn(
                    'basis-0 transition-[flex-grow] duration-300 ease-out motion-reduce:duration-0',
                    isAi && isContent ? 'grow overflow-y-auto' : 'grow-0 overflow-hidden'
                )}
            >
                {isAi && <HomepageThread />}
            </div>

            {/* Top separator — hidden in search (flush to top edge) */}
            <div
                className={cn(
                    'border-b transition-opacity duration-200 motion-reduce:duration-0',
                    !isIdle && !isSearch && phaseAtLeast(animationPhase, 'separator') ? 'opacity-100' : 'opacity-0'
                )}
            />

            {/* Input — always rendered, position determined by spacers */}
            <HomepageInput />

            {/* Bottom separator — hidden in AI (flush to bottom edge) */}
            <div
                className={cn(
                    'border-b transition-opacity duration-200 motion-reduce:duration-0',
                    !isIdle && !isAi && phaseAtLeast(animationPhase, 'separator') ? 'opacity-100' : 'opacity-0'
                )}
            />

            {/* Results container — always present, grows via flex when search content phase */}
            <div
                className={cn(
                    'basis-0 transition-[flex-grow] duration-300 ease-out motion-reduce:duration-0',
                    isSearch && isContent ? 'grow overflow-y-auto' : 'grow-0 overflow-hidden'
                )}
            >
                {isSearch && <HomepageSearchResults />}
            </div>

            {/* Bottom spacer — grows in idle (centering) and search pre-content (pushes input to top) */}
            <div
                className={cn(
                    'basis-0 transition-[flex-grow] duration-300 ease-out motion-reduce:duration-0',
                    isIdle || (isSearch && !isContent) ? 'grow' : 'grow-0'
                )}
            />
        </div>
    )
}
