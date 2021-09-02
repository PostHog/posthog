import React, { useEffect } from 'react'
import { useValues } from 'kea'
import { toursLogic } from '~/toolbar/tours/toursLogic'
import Shepherd from 'shepherd.js'
import { TourStepType } from '~/toolbar/types'
import { getShadowRootPopupContainer } from '~/toolbar/utils'

let tour: Shepherd.Tour

export function PreviewTour(): JSX.Element {
    const { onPreviewTour, params } = useValues(toursLogic)

    useEffect(() => {
        if (onPreviewTour) {
            tour = new Shepherd.Tour({
                defaultStepOptions: {
                    cancelIcon: {
                        enabled: true,
                    },
                    classes: 'shepherd-tour-card',
                    scrollTo: { behavior: 'smooth', block: 'center' },
                },
                stepsContainer: getShadowRootPopupContainer(),
                useModalOverlay: false,
            })

            ;(params?.steps ?? [])
                .filter((s: TourStepType) => !s.is_new_step)
                .forEach((step, i) => {
                    tour.addStep({
                        title: step?.tooltip_title ?? 'Step 1',
                        text: step?.tooltip_text ?? 'How it works',
                        attachTo: {
                            element: step?.html_el,
                            on: 'right',
                        },
                        buttons: [
                            {
                                action() {
                                    return this.back()
                                },
                                classes: 'shepherd-button-secondary',
                                text: 'Back',
                            },
                            {
                                action() {
                                    return this.next()
                                },
                                text: 'Next',
                            },
                        ],
                        id: `step-${i}`,
                    })
                })
            tour.start()

            return () => {
                tour.complete()
            }
        }
    }, [onPreviewTour])

    return (
        <>
            {/*{onPreviewTour && (*/}
            {/*    <div*/}
            {/*        style={{*/}
            {/*            position: 'fixed',*/}
            {/*            left: 0,*/}
            {/*            bottom: 0,*/}
            {/*            width: '100vw',*/}
            {/*            height: '100vh',*/}
            {/*            backgroundColor: 'rgba(0,0,0,0.2)',*/}
            {/*        }}*/}
            {/*    >*/}
            {/*        Hello*/}
            {/*    </div>*/}
            {/*)}*/}
        </>
    )
}
