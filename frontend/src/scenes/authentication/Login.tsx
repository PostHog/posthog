import { Col, Row } from 'antd'
import React from 'react'
import smLogo from 'public/icon-white.svg'
import './Login.scss'

export function Login(): JSX.Element {
    return (
        <div className="login">
            <Row>
                <Col span={24} md={10} className="image-showcase-container">
                    <div className="image-showcase ant-col-24 ant-col-md-10">
                        <div className="the-mountains" />
                        <div className="main-logo">
                            <img src={smLogo} alt="" />
                        </div>
                        <div className="showcase-content" />
                    </div>
                </Col>
                <Col span={24} md={14}>
                    Hello
                </Col>
            </Row>
        </div>
    )
}
