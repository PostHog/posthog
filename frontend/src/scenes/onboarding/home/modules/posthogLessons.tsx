import { Card, Carousel, Divider, Image, Space, Tooltip, Typography } from 'antd'
import React from 'react'
import { ArrowLeftOutlined, ArrowRightOutlined } from '@ant-design/icons'
import '../home.scss'

const { Paragraph } = Typography

const LESSONS = [
    {
        title: 'Event Tracking Overview',
        hover: 'A complete guide to getting started with event tracking.',
        target: 'https://posthog.com/docs/tutorials/actions',
        imgSrc: 'https://posthog.imgix.net/static/actions-087ad7af3bdb1b4ff329fe7360a952cb.png',
    },
    {
        title: 'Safely Roll Out New Features',
        hover: "A walk-through on how you can roll-out and learn from features using PostHog's feature flags.",
        target: 'https://posthog.com/docs/tutorials/feature-flags',
        imgSrc: 'https://posthog.imgix.net/static/feature-flags-1e8c20eefc3f0f8e8e72c0ce8101afcf.png',
    },
    {
        title: 'Funnels - Analyzing Conversions',
        hover: 'A walk-through on funnel analysis – a core component to learning about your product.',
        target: 'https://posthog.com/docs/tutorials/funnels',
        imgSrc: 'https://posthog.imgix.net/static/funnels-e83cb9084e9ad9d2347b6d09fba07605.png',
    },
    {
        title: 'Custom Behavioral Cohorts',
        hover:
            'A walk through on how you can analyze sets of users in groups based on behaviors or properties that you define.',
        target: 'https://posthog.com/docs/tutorials/cohorts',
        imgSrc: 'https://posthog.imgix.net/static/cohorts-ee2b05a043bd20bbfed442b6e75cb116.png',
    },
    {
        title: 'Measuring Retention',
        hover: 'A walk-through on answering a question every company must ask itself: Are users coming back?',
        target: 'https://posthog.com/docs/tutorials/retention',
        imgSrc: 'https://posthog.imgix.net/static/retention-2953b09ec29117beca1980e131abb1c1.png',
    },
    {
        title: 'Tracking Single Page Applications',
        hover: 'Implement PostHog into single page applications such as AngularJS.',
        target: 'https://posthog.com/docs/tutorials/spa',
        imgSrc: 'https://posthog.imgix.net/static/spa-4247169cea97603aa7f1d01afcbbed6e.png',
    },
    {
        title: 'Revenue Tracking',
        hover: 'A guide on how you can use PostHog to track subscribers and revenue over time.',
        target: 'https://posthog.com/docs/tutorials/revenue',
        imgSrc: 'https://posthog.imgix.net/static/revenue-6f73a5bb58cd615990431d854194bd80.png',
    },

    {
        title: 'Tracking Key B2B Product Metrics',
        hover: 'A guide on how B2B companies can implement successful analytics strategies.',
        target: 'https://posthog.com/docs/tutorials/b2b',
        imgSrc: 'https://posthog.imgix.net/static/b2b-028c24071e6d8bd3cedfcac068a4e02f.png',
    },
    {
        title: 'Tracking Team Usage',
        hover: 'Track how organizations use your product.',
        target: 'https://posthog.com/docs/tutorials/tracking-teams',
        imgSrc: 'https://posthog.imgix.net/static/user-model-bc991a8cc7e060a6e9495289082cdb98.png?w=1400',
    },
]

function Tutorials(): JSX.Element {
    const settings = {
        dots: true,
        slidesToShow: 4,
        slidesToScroll: 2,
        arrows: true,
        nextArrow: <ArrowRightOutlined />,
        prevArrow: <ArrowLeftOutlined />,
        autoplay: true,
        vertical: false,
        autoplaySpeed: 7500,
        centerMode: true,
        centerPadding: '10px',
        responsive: [
            {
                breakpoint: 1400,
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
                },
            },
        ],
    }

    const thumbs = LESSONS.map((lesson) => (
        <a key={lesson.target} href={lesson.target} target="_blank">
            <Tooltip title={lesson.hover ?? ''} placement={'bottom'}>
                <Card className={'lesson-card'} bordered={false}>
                    <Image src={lesson.imgSrc} className="lesson-image" width={225} preview={false} />
                    <h4 className={'lesson-title'}>{lesson.title}</h4>
                </Card>
            </Tooltip>
        </a>
    ))

    return (
        <Carousel {...settings} className={'tutorials-carousel'}>
            {thumbs}
        </Carousel>
    )
}

export function PostHogLessons(): JSX.Element {
    return (
        <Card className="home-module-card">
            <h2 id="name" className="subtitle">
                Product Analytics Tutorials
            </h2>
            <Paragraph>
                Quick tutorials and short guides on how PostHog can help you use product analytics effectively. Written
                by us, based on you.
            </Paragraph>
            <Divider />
            <Space direction={'vertical'}>
                <div className="home-module-carousel-container">
                    <Tutorials />
                </div>
            </Space>
        </Card>
    )
}
