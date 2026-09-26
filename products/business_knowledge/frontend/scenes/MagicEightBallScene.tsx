import './MagicEightBall.scss'

import { useActions, useValues } from 'kea'
import { Fragment, useEffect, useRef, useState } from 'react'

import { IconBook } from '@posthog/icons'
import { LemonButton, LemonInput, Link, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { Region } from '~/types'

import { BusinessKnowledgeTabs } from '../components/BusinessKnowledgeTabs'
import { magicEightBallLogic } from './magicEightBallLogic'

export const scene: SceneExport = {
    component: MagicEightBallScene,
    logic: magicEightBallLogic,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
}

// accelerationIncludingGravity sits near 9.8 at rest; a deliberate shake goes well past this.
const SHAKE_THRESHOLD = 25
const SHAKE_QUIET_MS = 1000

/** iOS Safari only fires devicemotion after this is granted from a tap. */
type MotionPermissionRequest = { requestPermission?: () => Promise<'granted' | 'denied'> }

function motionNeedsPermission(): boolean {
    return (
        typeof DeviceMotionEvent !== 'undefined' &&
        typeof (DeviceMotionEvent as unknown as MotionPermissionRequest).requestPermission === 'function'
    )
}

function useShake(onShake: () => void, enabled: boolean): void {
    const onShakeRef = useRef(onShake)
    onShakeRef.current = onShake

    useEffect(() => {
        if (!enabled) {
            return
        }
        let armed = true
        let lastPeak = 0
        const handleMotion = (event: DeviceMotionEvent): void => {
            const acceleration = event.accelerationIncludingGravity
            if (!acceleration) {
                return
            }
            const { x, y, z } = acceleration
            const force = Math.sqrt((x ?? 0) ** 2 + (y ?? 0) ** 2 + (z ?? 0) ** 2)
            const now = Date.now()
            if (force > SHAKE_THRESHOLD) {
                lastPeak = now
                if (armed) {
                    armed = false
                    onShakeRef.current()
                }
            } else if (now - lastPeak > SHAKE_QUIET_MS) {
                armed = true
            }
        }
        window.addEventListener('devicemotion', handleMotion)
        return () => window.removeEventListener('devicemotion', handleMotion)
    }, [enabled])
}

export function MagicEightBallScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { featureFlagsTimedOut } = useValues(appLogic)
    const { preflight } = useValues(preflightLogic)
    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }
    if (
        !preflight?.is_debug &&
        (preflight?.region !== Region.US || !featureFlags[FEATURE_FLAGS.ML_INFERENCE_DECISIONS])
    ) {
        return receivedFeatureFlags || featureFlagsTimedOut ? (
            <NotFound object="Magic 8 ball" caption="The decision model is not enabled for this project." />
        ) : (
            <Spinner className="text-3xl mx-auto my-8" />
        )
    }
    return <MagicEightBall />
}

function MagicEightBall(): JSX.Element {
    const { question, result, askError, resultLoading, askDisabledReason } = useValues(magicEightBallLogic)
    const { setQuestion, ask } = useActions(magicEightBallLogic)
    const [motionAllowed, setMotionAllowed] = useState(() => !motionNeedsPermission())
    const [answeredQuestion, setAnsweredQuestion] = useState<string | null>(null)

    const tryAsk = (): void => {
        if (!askDisabledReason) {
            setAnsweredQuestion(question.trim())
            ask()
        }
    }
    useShake(tryAsk, motionAllowed)

    const requestMotion = async (): Promise<void> => {
        try {
            const permission = await (DeviceMotionEvent as unknown as MotionPermissionRequest).requestPermission?.()
            setMotionAllowed(permission === 'granted')
        } catch {
            setMotionAllowed(false)
        }
    }

    const matchesQuestion = answeredQuestion === question.trim()
    const reveal = matchesQuestion && !askError ? result?.answer : null
    const showResult = matchesQuestion && !!result && !askError && !resultLoading

    return (
        <SceneContent>
            <SceneTitleSection
                name="Magic 8 ball"
                description="Ask a product question. The ball answers from your business knowledge."
                resourceType={{ type: 'default_icon_type', forceIcon: <IconBook /> }}
            />
            <BusinessKnowledgeTabs activeTab="magic-eight-ball" />
            <div className="flex flex-col items-center gap-6 py-6">
                <div className="w-full max-w-xl">
                    <LemonInput
                        value={question}
                        onChange={(nextQuestion) => {
                            setQuestion(nextQuestion)
                            setAnsweredQuestion(null)
                        }}
                        onPressEnter={tryAsk}
                        placeholder="Do we offer refunds on annual plans?"
                        autoFocus
                        fullWidth
                        maxLength={500}
                        disabled={resultLoading}
                        data-attr="magic-eight-ball-question"
                    />
                </div>
                <button
                    type="button"
                    className={`MagicEightBall${resultLoading ? ' MagicEightBall--shaking' : ''}`}
                    onClick={tryAsk}
                    aria-label="Shake the magic 8 ball"
                    aria-busy={resultLoading}
                    disabled={!!askDisabledReason}
                    data-attr="magic-eight-ball"
                >
                    <div className="MagicEightBall__window" aria-live="polite">
                        {resultLoading ? null : reveal ? (
                            <div className="MagicEightBall__triangle">
                                <span>{reveal}</span>
                            </div>
                        ) : (
                            <div className="MagicEightBall__eight">8</div>
                        )}
                    </div>
                </button>
                <span role="status" className="sr-only">
                    {resultLoading ? null : askError ? `The ball couldn't answer: ${askError}` : reveal}
                </span>
                <div className="flex flex-col items-center gap-1 text-secondary text-center">
                    {askError ? (
                        <span>The ball couldn't answer: {askError}</span>
                    ) : showResult ? (
                        <>
                            <span>
                                The ball was <span translate="no">{Math.round(result.confidence * 100)}%</span> sure.
                            </span>
                            {result.sources.length > 0 ? (
                                <span className="text-sm">
                                    Drawn from{' '}
                                    {result.sources.map((source, index) => (
                                        <Fragment key={`${source.source_id}:${index}`}>
                                            {index > 0 && ', '}
                                            <Link to={urls.businessKnowledgeSource(source.source_id)}>
                                                {source.document_title || source.source_name}
                                            </Link>
                                        </Fragment>
                                    ))}
                                </span>
                            ) : (
                                <span className="text-sm">
                                    Nothing in your business knowledge matched, so the ball cannot answer.
                                </span>
                            )}
                        </>
                    ) : (
                        <span>Type a question, then shake your phone, tap the ball or press Enter.</span>
                    )}
                </div>
                {!motionAllowed && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => void requestMotion()}
                        data-attr="magic-eight-ball-motion"
                    >
                        Enable shake to ask
                    </LemonButton>
                )}
            </div>
        </SceneContent>
    )
}
