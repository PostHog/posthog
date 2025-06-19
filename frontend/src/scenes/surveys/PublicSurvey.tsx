import { useValues } from 'kea'
import { router } from 'kea-router'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

interface SurveyData {
    survey: {
        id: string
        name: string
        type: string
        questions: any[]
        appearance: any
        start_date: string | null
        end_date: string | null
    }
    project_config: {
        api_host: string
        token: string
    }
}

export const scene: SceneExport = {
    component: PublicSurvey,
}

export function PublicSurvey(): JSX.Element {
    const { location } = useValues(router)

    // Parse URL parameters - expecting format: /surveys/public/{surveyId}?token={token}
    const pathParts = location.pathname.split('/')
    const surveyId = pathParts[pathParts.length - 1] // Last part of the path
    const urlParams = new URLSearchParams(location.search)
    const apiToken = urlParams.get('token')

    const [surveyData, setSurveyData] = useState<SurveyData | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const surveyContainerRef = useRef<HTMLDivElement>(null)
    const posthogInitialized = useRef(false)

    useEffect(() => {
        async function fetchSurveyData(): Promise<void> {
            if (!surveyId || !apiToken) {
                setError('Invalid survey URL')
                setLoading(false)
                return
            }

            try {
                // Use the existing endpoint format that's already working
                const response = await fetch(`/api/surveys/${surveyId}/?token=${apiToken}`)

                if (!response.ok) {
                    if (response.status === 404) {
                        setError('Survey not found')
                    } else if (response.status === 403) {
                        setError('This survey is not available for public access')
                    } else {
                        setError('Failed to load survey')
                    }
                    setLoading(false)
                    return
                }

                const data: SurveyData = await response.json()
                setSurveyData(data)
                setLoading(false)
            } catch (err) {
                console.error('Error fetching survey:', err)
                setError('Failed to load survey')
                setLoading(false)
            }
        }

        void fetchSurveyData()
    }, [surveyId, apiToken])

    useEffect(() => {
        if (surveyData && !posthogInitialized.current && surveyContainerRef.current) {
            // Initialize PostHog with the project's configuration
            posthog.init(surveyData.project_config.token, {
                api_host: surveyData.project_config.api_host,
                loaded: () => {
                    // Once PostHog is loaded, render the survey
                    if (surveyContainerRef.current) {
                        posthog.renderSurvey(surveyData.survey.id, surveyContainerRef.current.id)
                    }
                },
            })
            posthogInitialized.current = true
        }
    }, [surveyData])

    if (loading) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-bg-3000">
                <div className="max-w-md w-full space-y-4 p-8">
                    <div className="text-center">
                        <Spinner className="w-8 h-8 mx-auto mb-4" />
                        <h2 className="text-xl font-semibold">Loading survey...</h2>
                    </div>
                    <LemonSkeleton className="h-4" />
                    <LemonSkeleton className="h-4" />
                    <LemonSkeleton className="h-4 w-3/4" />
                </div>
            </div>
        )
    }

    if (error) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-bg-3000">
                <div className="max-w-md w-full text-center p-8">
                    <div className="text-6xl mb-4">📋</div>
                    <h1 className="text-2xl font-bold mb-2">Survey Unavailable</h1>
                    <p className="text-muted mb-6">{error}</p>
                    <p className="text-sm text-muted-alt">
                        If you believe this is an error, please contact the survey creator.
                    </p>
                </div>
            </div>
        )
    }

    if (!surveyData) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-bg-3000">
                <div className="max-w-md w-full text-center p-8">
                    <div className="text-6xl mb-4">📋</div>
                    <h1 className="text-2xl font-bold mb-2">Survey Not Found</h1>
                    <p className="text-muted">This survey could not be loaded.</p>
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-bg-3000">
            <div className="max-w-4xl mx-auto py-8 px-4">
                <div className="text-center mb-8">
                    <h1 className="text-3xl font-bold text-text-3000 mb-2">{surveyData.survey.name}</h1>
                    <p className="text-muted">Please take a moment to share your feedback</p>
                </div>

                {/* Container where posthog-js will render the survey */}
                <div
                    ref={surveyContainerRef}
                    id="posthog-survey-container"
                    className="w-full min-h-[400px] flex items-center justify-center"
                />
            </div>
        </div>
    )
}
