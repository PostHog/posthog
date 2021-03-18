import { Col, Row } from 'antd'
import React from 'react'
import './AuthenticationView.scss'
import smLogo from 'public/icon-white.svg'
interface AuthenticationViewProps {
    mainContent: JSX.Element
    sideContent?: JSX.Element
    parentContainerRef?: React.Ref<HTMLDivElement>
    mainContainerRef?: React.Ref<HTMLDivElement>
}

export function AuthenticationView({
    mainContent,
    sideContent,
    parentContainerRef,
    mainContainerRef,
}: AuthenticationViewProps): JSX.Element {
    /*
    General UI view for authentication scenes (login, signup & invite signup)
    */

    return (
        <div className="authentication-view" ref={parentContainerRef}>
            <Row>
                <Col span={24} md={10} className="image-showcase-container">
                    <div className="image-showcase ant-col-24 ant-col-md-10">
                        <div className="the-mountains" />
                        <div className="main-logo">
                            <img src={smLogo} alt="" />
                        </div>
                        <div className="showcase-content">{sideContent}</div>
                    </div>
                </Col>
                <Col span={24} md={14} className="rhs-content" ref={mainContainerRef}>
                    <div className="rhs-inner">{mainContent}</div>
                </Col>
            </Row>
        </div>
    )
}
