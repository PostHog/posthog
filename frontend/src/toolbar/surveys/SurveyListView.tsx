import { useValues, useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonInput, LemonButton, Spinner } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { Survey } from '~/types'

import { ToolbarMenu } from '../bar/ToolbarMenu'
import { SurveyRow } from './SurveyRow'
import { surveysToolbarLogic } from './surveysToolbarLogic'

export function SurveyListView(): JSX.Element {
    const { searchTerm, allSurveys, allSurveysLoading, hasMoreSurveys } = useValues(surveysToolbarLogic)
    const { setSearchTerm, loadSurveys, loadMoreSurveys, startQuickCreate } = useActions(surveysToolbarLogic)

    useOnMountEffect(() => {
        loadSurveys()
    })

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <div className="flex gap-1 items-center w-full">
                    <LemonInput
                        autoFocus
                        placeholder="Search surveys"
                        fullWidth
                        type="search"
                        size="small"
                        value={searchTerm}
                        onChange={(s) => setSearchTerm(s)}
                    />
                    <LemonButton
                        size="small"
                        type="primary"
                        icon={<IconPlus />}
                        onClick={startQuickCreate}
                        tooltip="Quick create survey"
                        className="flex-shrink-0"
                    />
                </div>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="mt-1">
                    {allSurveysLoading && allSurveys.length === 0 ? (
                        <div className="flex justify-center py-4">
                            <Spinner className="text-2xl" />
                        </div>
                    ) : allSurveys.length > 0 ? (
                        <>
                            {allSurveys.map((survey: Survey) => (
                                <SurveyRow key={survey.id} survey={survey} />
                            ))}
                            {hasMoreSurveys && (
                                <div className="flex justify-center py-2">
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        loading={allSurveysLoading}
                                        onClick={loadMoreSurveys}
                                    >
                                        Load more
                                    </LemonButton>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="text-muted text-sm text-center py-4">
                            {searchTerm ? 'No matching surveys found.' : 'No surveys found in this project.'}
                        </div>
                    )}
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}
