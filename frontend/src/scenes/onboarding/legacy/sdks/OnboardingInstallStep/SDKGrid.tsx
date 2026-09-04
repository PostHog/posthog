import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonTabs } from '@posthog/lemon-ui'

import { InviteMembersButton } from 'lib/components/Account/InviteMembersButton'
import { FeedbackSurveyButton } from 'lib/components/FeedbackSurveyButton/FeedbackSurveyButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { SDKTag } from '~/types'

import { NextButton } from './NextButton'
import { SDKGridProps } from './types'

// Collects feedback on SDKs we don't support yet.
// https://us.posthog.com/project/2/surveys/019b47ab-5f19-0000-7f31-4f9681cde589
const MISSING_SDK_SURVEY_ID = '019b47ab-5f19-0000-7f31-4f9681cde589'

export function SDKGrid({
    filteredSDKs,
    searchTerm,
    selectedTag,
    tags,
    onSDKClick,
    onSearchChange,
    onTagChange,
    currentTeam,
    showTopControls = true,
    installationComplete,
    showTopSkipButton,
}: SDKGridProps): JSX.Element {
    const hasNarrowed = !!searchTerm || !!selectedTag
    const noResults = hasNarrowed && (filteredSDKs ?? []).length === 0

    const clearFilters = (): void => {
        onSearchChange('')
        onTagChange(null)
    }
    return (
        <div className="flex flex-col gap-y-4">
            <div className="flex flex-col gap-y-2">
                {showTopControls && (
                    <div className="flex flex-col-reverse md:flex-row justify-between gap-4">
                        <LemonInput
                            value={searchTerm}
                            onChange={onSearchChange}
                            placeholder="Search"
                            className="w-full max-w-[220px]"
                        />
                        <div className="flex flex-row flex-wrap gap-2">
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={() => void copyToClipboard(currentTeam?.api_token || '', 'Project token')}
                                icon={<IconCopy />}
                                data-attr="copy-project-token"
                            >
                                Copy project token
                            </LemonButton>
                            <InviteMembersButton
                                type="primary"
                                size="small"
                                fullWidth={false}
                                text="Invite developer"
                            />
                            {showTopSkipButton && (
                                <NextButton size="small" installationComplete={installationComplete} />
                            )}
                        </div>
                    </div>
                )}
                <LemonTabs
                    activeKey={selectedTag ?? 'All'}
                    onChange={(key) => onTagChange(key === 'All' ? null : (key as SDKTag))}
                    tabs={tags.map((tag) => ({
                        key: tag,
                        label: tag,
                    }))}
                />
                {noResults ? (
                    <LemonCard className="p-4 flex flex-col items-start gap-2">
                        <strong>No SDKs match your search</strong>
                        <span className="text-muted">
                            Try a different term or clear your filters to see everything. Don&apos;t see your SDK? Let
                            us know what you need.
                        </span>
                        <div className="flex flex-row flex-wrap gap-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={clearFilters}
                                data-attr="onboarding-show-all-sdks"
                            >
                                Show all SDKs
                            </LemonButton>
                            <FeedbackSurveyButton
                                surveyId={MISSING_SDK_SURVEY_ID}
                                data-attr="onboarding-reach-out-to-us-button"
                                label="Reach out to us"
                                properties={{ feedback_surface: 'onboarding_install', searched_term: searchTerm }}
                            />
                        </div>
                    </LemonCard>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        {(filteredSDKs ?? []).map((sdk) => (
                            <LemonCard
                                key={sdk.key}
                                className="p-4 cursor-pointer flex flex-col items-start justify-center"
                                onClick={() => onSDKClick(sdk)}
                            >
                                <div className="w-8 h-8 mb-2">
                                    {typeof sdk.image === 'string' ? (
                                        <img src={sdk.image} className="w-8 h-8" alt={`${sdk.name} logo`} />
                                    ) : typeof sdk.image === 'object' && 'default' in sdk.image ? (
                                        <img src={sdk.image.default} className="w-8 h-8" alt={`${sdk.name} logo`} />
                                    ) : (
                                        sdk.image
                                    )}
                                </div>

                                <strong>{sdk.name}</strong>
                            </LemonCard>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
