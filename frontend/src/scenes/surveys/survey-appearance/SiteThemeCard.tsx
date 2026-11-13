import clsx from 'clsx'
import { useValues } from 'kea'
import { ReactNode, useEffect, useRef, useState } from 'react'

import { IconBrowser } from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { NewSurvey, SurveyTheme } from 'scenes/surveys/constants'
import { THEME_CARD_INTERACTION, ThemePreviewCard } from 'scenes/surveys/wizard/SurveyThemeSelector'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Survey, SurveyAppearance, SurveyType } from '~/types'

import {
    siteSnapshotUrlCondition,
    surveySiteSnapshotLogic,
} from 'products/surveys/frontend/draftReview/surveySiteSnapshotLogic'

import { siteTheme } from './siteTheme'

const SURVEY_TYPES_ON_SITE = [SurveyType.Popover, SurveyType.Widget]

function isSaved(survey: Survey | NewSurvey): survey is Survey {
    return survey.id !== 'new'
}

interface SiteThemeCardProps {
    survey: Survey
    appearance: SurveyAppearance
    onSelectTheme: (theme: SurveyTheme) => void
    disabled?: boolean
}

function SiteCard({
    description,
    onClick,
    loading,
    disabled,
    focusOnMount,
    children,
}: {
    description: string
    onClick?: () => void
    loading?: boolean
    disabled?: boolean
    focusOnMount?: boolean
    children?: ReactNode
}): JSX.Element {
    const ref = useRef<HTMLButtonElement & HTMLDivElement>(null)
    useEffect(() => {
        if (focusOnMount) {
            ref.current?.focus()
        }
    }, [focusOnMount])

    const className = clsx(
        'flex flex-col rounded-lg border-2 border-dashed border-border bg-bg-light p-2 text-left',
        THEME_CARD_INTERACTION,
        onClick && !disabled && 'hover:border-primary/50',
        disabled && 'cursor-not-allowed opacity-50'
    )
    const body = (
        <>
            <div className="mb-1.5 flex h-14 w-full items-center justify-center rounded border text-2xl text-secondary">
                {loading ? <Spinner /> : <IconBrowser />}
            </div>
            <span className="text-sm font-medium">Match my site</span>
            <span className="text-xs text-muted" role={onClick ? undefined : 'status'}>
                {description}
            </span>
            {children}
        </>
    )
    return onClick ? (
        <button ref={ref} type="button" onClick={onClick} disabled={disabled} className={className}>
            {body}
        </button>
    ) : (
        <div ref={ref} tabIndex={-1} className={className}>
            {body}
        </div>
    )
}

function LoadedSiteThemeCard({ survey, appearance, onSelectTheme, disabled }: SiteThemeCardProps): JSX.Element {
    const { siteSnapshot, gaveUp } = useValues(
        surveySiteSnapshotLogic({
            surveyId: survey.id,
            device: 'desktop',
            urlCondition: siteSnapshotUrlCondition(survey.conditions),
        })
    )

    if (siteSnapshot?.status === 'unavailable') {
        return <SiteCard description="Needs a recent recording of this page" focusOnMount />
    }
    if (!siteSnapshot?.site_style) {
        return gaveUp || siteSnapshot?.status === 'ready' ? (
            <SiteCard description="Couldn't read your site's colors. Try a preset." focusOnMount />
        ) : (
            <SiteCard description="Reading your site. This can take a minute." loading focusOnMount />
        )
    }
    const theme = siteTheme(siteSnapshot.site_style)
    return (
        <ThemePreviewCard
            theme={theme}
            isSelected={
                appearance.backgroundColor === theme.appearance.backgroundColor &&
                appearance.submitButtonColor === theme.appearance.submitButtonColor
            }
            onClick={() => onSelectTheme(theme)}
            disabled={disabled}
            autoFocus
        />
    )
}

function SiteThemeCard(props: SiteThemeCardProps): JSX.Element {
    const [requested, setRequested] = useState(false)
    const { currentTeam } = useValues(teamLogic)

    if (!SURVEY_TYPES_ON_SITE.includes(props.survey.type)) {
        return <SiteCard description="Only for surveys shown on your website" />
    }
    if (!currentTeam?.session_recording_opt_in) {
        return (
            <SiteCard description="Uses session replay to read your site.">
                <Link to={urls.settings('environment-replay', 'replay')} target="_blank" className="text-xs">
                    Turn on session replay
                </Link>
            </SiteCard>
        )
    }
    return requested ? (
        <LoadedSiteThemeCard {...props} />
    ) : (
        <SiteCard description="Use your site's colors" onClick={() => setRequested(true)} disabled={props.disabled} />
    )
}

/** The "Match my site" theme card, or null where it does not apply, so the theme grid can count its cards. */
export function useSiteThemeCard({
    survey,
    ...props
}: Omit<SiteThemeCardProps, 'survey'> & { survey: Survey | NewSurvey }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.SURVEYS_MATCH_MY_SITE] && isSaved(survey) ? (
        <SiteThemeCard survey={survey} {...props} />
    ) : null
}
