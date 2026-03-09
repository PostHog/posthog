import { BindLogic, useValues } from 'kea'

import { Search } from 'lib/components/Search/Search'
import { cn } from 'lib/utils/css-classes'
import { maxLogic } from 'scenes/max/maxLogic'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'
import { HOMEPAGE_TAB_ID } from './constants'
import { HomepageInput } from './HomepageInput'
import { HomepageSearchResults } from './HomepageSearchResults'
import { HomepageThread } from './HomepageThread'

const PHASE_ORDER = ['idle', 'moving', 'separator', 'content'] as const

function phaseAtLeast(current: string, target: string): boolean {
    return PHASE_ORDER.indexOf(current as any) >= PHASE_ORDER.indexOf(target as any)
}

export function AiFirstHomepage(): JSX.Element {
    const { mode, animationPhase, query } = useValues(aiFirstHomepageLogic)

    const isIdle = mode === 'idle'
    const isAi = mode === 'ai'
    const isSearch = mode === 'search'
    const isContent = animationPhase === 'content'

    return (
        <BindLogic logic={maxLogic} props={{ tabId: HOMEPAGE_TAB_ID }}>
            <Search.Root
                logicKey="homepage"
                showAskAiLink={false}
                isActive={isSearch}
                defaultSearchValue={isSearch ? query : ''}
                className="grow overflow-hidden h-full"
            >
                <div className="flex flex-col grow overflow-hidden h-full">
                    {/* Top spacer — grows in idle (centering), collapses for AI and search */}
                    <div
                        className={cn(
                            'basis-0 transition-[flex-grow] duration-300 ease-out motion-reduce:duration-0',
                            isIdle || (isAi && !isContent) ? 'grow' : 'grow-0'
                        )}
                    />

                    {/* Thread container — fades in when AI content phase */}
                    <div
                        className={cn(
                            'basis-0 min-h-0 flex flex-col transition-opacity duration-300 ease-out motion-reduce:duration-0',
                            isAi && isContent ? 'grow opacity-100' : 'grow-0 opacity-0'
                        )}
                    >
                        {isAi && <HomepageThread />}
                    </div>

                    {/* Top separator — hidden in search (flush to top edge) */}
                    <div
                        className={cn(
                            'border-b transition-opacity duration-200 motion-reduce:duration-0',
                            !isIdle && !isSearch && phaseAtLeast(animationPhase, 'separator')
                                ? 'opacity-100'
                                : 'opacity-0'
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

                    {/* Results container — fades in when search content phase */}
                    <div
                        className={cn(
                            'basis-0 min-h-0 flex flex-col transition-opacity duration-300 ease-out motion-reduce:duration-0',
                            isSearch && isContent ? 'grow opacity-100' : 'grow-0 opacity-0'
                        )}
                    >
                        {isSearch && <HomepageSearchResults />}
                    </div>

                    {/* Bottom spacer — grows in idle (centering), collapses for search and AI */}
                    <div
                        className={cn(
                            'basis-0 transition-[flex-grow] duration-300 ease-out motion-reduce:duration-0',
                            isIdle || (isSearch && !isContent) ? 'grow' : 'grow-0'
                        )}
                    />
                </div>
            </Search.Root>
        </BindLogic>
    )
}
