import './PlayerMeta.scss'
import React from 'react'
import { Col, Row } from 'antd'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { useValues } from 'kea'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { PersonHeader } from 'scenes/persons/PersonHeader'

export function PlayerMeta(): JSX.Element {
    const { sessionPerson } = useValues(sessionRecordingLogic)

    return (
        <Col className="player-meta-container">
            <Row className="player-meta-person" align="middle" justify="space-between">
                <Row>
                    <ProfilePicture
                        name={person?.name ?? 'Unidentified user'}
                        email={person?.properties?.$email}
                        size="sm"
                    />
                    <PersonHeader person={person} withIcon={false} />
                </Row>
                <Col>time</Col>
            </Row>
            <Row className="player-meta-other" align="middle" justify="space-between">
                <Col>
                    <Row>Browser</Row>
                    <Row>Resolution</Row>
                </Col>
            </Row>
        </Col>
    )
}
