import { Card, Carousel, Divider, Image, Space, Spin, Typography } from 'antd'
import React, { useState } from 'react'
import { Tooltip } from 'lib/components/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useActions } from 'kea'

const { Paragraph } = Typography

import eventTrackingOverview from 'scenes/onboarding/home/static/event-tracking-overview.png'
import rollOutFeatures from 'scenes/onboarding/home/static/roll-out-features.png'
import analyzeConversions from 'scenes/onboarding/home/static/analyze-conversions.png'
import analyzeBehavior from 'scenes/onboarding/home/static/analyzing-behavior.png'
import measureRetention from 'scenes/onboarding/home/static/measure-retention.png'
import trackingSpas from 'scenes/onboarding/home/static/tracking-spas.png'
import salesRevenueTracking from 'scenes/onboarding/home/static/sales-revenue-tracking.png'
import trackingB2b from 'scenes/onboarding/home/static/tracking-b2b.png'
import trackingTeams from 'scenes/onboarding/home/static/tracking-teams.png'
import { CarouselArrow } from 'scenes/onboarding/home/sections/CarouselArrow'

const UTM_TAGS = '?utm_medium=in-product&utm_campaign=project-home'

const LESSONS = [
    {
        title: 'Event Tracking Overview',
        hover: 'A complete guide to getting started with event tracking.',
        target: `https://posthog.com/docs/tutorials/actions${UTM_TAGS}`,
        imgSrc: eventTrackingOverview,
    },
    {
        title: 'Safely Roll Out New Features',
        hover: "A walk-through on how you can roll-out and learn from features using PostHog's feature flags.",
        target: `https://posthog.com/docs/tutorials/feature-flags?utm_content=project-homes${UTM_TAGS}`,
        imgSrc: rollOutFeatures,
    },
    {
        title: 'Funnels - Analyzing Conversions',
        hover: 'A walk-through on funnel analysis – a core component to learning about your product.',
        target: `https://posthog.com/docs/tutorials/funnels?utm_content=project-home${UTM_TAGS}`,
        imgSrc: analyzeConversions,
    },
    {
        title: 'Custom Behavioral Cohorts',
        hover:
            'A walk-through on how you can analyze sets of users in groups based on behaviors or properties that you define.',
        target: `https://posthog.com/docs/tutorials/cohorts?utm_content=project-home${UTM_TAGS}`,
        imgSrc: analyzeBehavior,
    },
    {
        title: 'Measuring Retention',
        hover: 'A walk-through on answering a question every company must ask itself: Are users coming back?',
        target: `https://posthog.com/docs/tutorials/retention?utm_content=project-home${UTM_TAGS}`,
        imgSrc: measureRetention,
    },
    {
        title: 'Tracking Single Page Applications',
        hover: 'Implement PostHog into single page applications such as AngularJS.',
        target: `https://posthog.com/docs/tutorials/spa${UTM_TAGS}`,
        imgSrc: trackingSpas,
    },
    {
        title: 'Revenue Tracking',
        hover: 'A guide on how you can use PostHog to track subscribers and revenue over time.',
        target: `https://posthog.com/docs/tutorials/revenue${UTM_TAGS}`,
        imgSrc: salesRevenueTracking,
    },

    {
        title: 'Tracking Key B2B Product Metrics',
        hover: 'A guide on how B2B companies can implement successful analytics strategies.',
        target: `https://posthog.com/docs/tutorials/b2b${UTM_TAGS}`,
        imgSrc: trackingB2b,
    },
    {
        title: 'Tracking Team Usage',
        hover: 'Track how organizations use your product.',
        target: `https://posthog.com/docs/tutorials/tracking-teams${UTM_TAGS}`,
        imgSrc: trackingTeams,
    },
]

function Tutorials(): JSX.Element {
    const { reportProjectHomeItemClicked } = useActions(eventUsageLogic)

    const settings = {
        dots: true,
        slidesToShow: 4,
        slidesToScroll: 3,
        arrows: true,
        nextArrow: <CarouselArrow direction="next" />,
        prevArrow: <CarouselArrow direction="prev" />,
        autoplay: true,
        vertical: false,
        autoplaySpeed: 5500,
        centerMode: true,
        centerPadding: '10px',
        responsive: [
            {
                breakpoint: 1200,
                settings: {
                    vertical: false,
                    centerMode: true,
                    slidesToShow: 3,
                },
            },
            {
                breakpoint: 1000,
                settings: {
                    vertical: false,
                    centerMode: true,
                    slidesToShow: 2,
                },
            },

            {
                breakpoint: 700,
                settings: {
                    vertical: false,

                    centerMode: true,
                    slidesToShow: 1,
                    slidesToScroll: 1,
                },
            },
        ],
    }

    const thumbs = LESSONS.map((lesson) => {
        const [isImageLoaded, setIsImageLoaded] = useState(false)
        return (
            <a
                key={lesson.target}
                href={lesson.target}
                target="_blank"
                rel="noopener"
                onClick={() => {
                    reportProjectHomeItemClicked('tutorials', lesson.title, { lesson_url: lesson.target })
                    return true
                }}
            >
                <Tooltip title={lesson.hover ?? ''} placement={'bottom'}>
                    <Card className={'home-page lesson-card'} bordered={false}>
                        <Spin spinning={!isImageLoaded}>
                            <Image
                                src={lesson.imgSrc}
                                onLoad={() => {
                                    setIsImageLoaded(true)
                                }}
                                className="lesson-image"
                                width={225}
                                preview={false}
                            />
                        </Spin>
                        <h4 className={'lesson-title'}>{lesson.title}</h4>
                    </Card>
                </Tooltip>
            </a>
        )
    })

    return <Carousel {...settings}>{thumbs}</Carousel>
}

export function PostHogLessons(): JSX.Element {
    return (
        <Card className="home-page section-card">
            <h2 id="name" className="subtitle">
                Build Better Products
            </h2>
            <Paragraph>
                Quick tutorials and exercises to help your team implement an effective product analytics strategy.
            </Paragraph>
            <Divider />
            <Space direction={'vertical'}>
                <div className="carousel-container">
                    <Tutorials />
                </div>
            </Space>
        </Card>
    )
}
