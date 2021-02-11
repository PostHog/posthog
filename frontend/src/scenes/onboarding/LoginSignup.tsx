import { Col, Row } from 'antd'
import React from 'react'
import './LoginSignup.scss'
import smLogo from 'public/icon-white.svg'

interface LoginSignupProps {
    showcaseCaption?: JSX.Element | string
}

export function LoginSignup({ showcaseCaption }: LoginSignupProps): JSX.Element {
    /*
    UI component for the login & signup pages.
    */
    return (
        <div className="login-signup">
            <Row>
                <Col span={10} className="image-showcase">
                    <div className="the-mountains" />
                    <div className="main-logo">
                        <img src={smLogo} alt="" />
                    </div>
                    <div className="showcase-content">
                        <h1 className="page-title">Join Hogflix at PostHog</h1>
                        <div className="showcase-caption">{showcaseCaption}</div>
                    </div>
                </Col>
                <Col span={14}>
                    <div className="social-logins">
                        <h2>Create your account with a provider</h2>
                        <div className="text-muted">One less password to manage</div>
                    </div>
                </Col>
            </Row>
        </div>
    )
}
