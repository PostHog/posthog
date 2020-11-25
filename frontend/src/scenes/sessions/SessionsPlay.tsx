import React, { useEffect, useRef } from 'react'
import { Player } from 'posthog-react-rrweb-player'
import { Card, Col, Input, Row, Tag } from 'antd'
import {
    AppleOutlined,
    ChromeOutlined,
    PushpinOutlined,
    UserOutlined,
    FieldTimeOutlined,
    PlusOutlined,
    SyncOutlined,
} from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { colorForString } from 'lib/utils'
import { Loading } from 'lib/utils'
import { sessionsPlayLogic } from './sessionsPlayLogic'
import { IconExternalLink } from 'lib/components/icons'
import './Sessions.scss'
import './SessionsPlayer.scss'

export const SessionsPlay = hot(_SessionsPlay)
function _SessionsPlay(): JSX.Element {
    const { sessionPlayerData, sessionPlayerDataLoading, addingTagShown, addingTag, tags, tagsLoading } = useValues(
        sessionsPlayLogic
    )
    const { toggleAddingTagShown, setAddingTag, createTag } = useActions(sessionsPlayLogic)
    const addTagInput = useRef<Input>(null)

    useEffect(() => {
        if (addingTagShown && addTagInput.current) {
            addTagInput.current.focus()
        }
    }, [addingTagShown])

    const removeTag = (tag: string): void => {
        alert(`removed tag ${tag}`)
    }
    // END TEMPORARY VALUES FOR TESTING

    return (
        <div className="session-player">
            <Row gutter={16} style={{ height: '100%' }}>
                <Col span={18} style={{ paddingRight: 0 }}>
                    <div className="mb-05">
                        <b>Current URL: </b> https://posthog.com/docs
                        <span className="float-right">
                            <ChromeOutlined /> Chrome on <AppleOutlined /> macOS (1400 x 600)
                        </span>
                    </div>
                    <div className="ph-no-capture player-container">
                        {sessionPlayerDataLoading ? <Loading /> : <Player events={sessionPlayerData!} />}
                    </div>
                </Col>
                <Col span={6} className="sidebar" style={{ paddingLeft: 16 }}>
                    <Card className="card-elevated">
                        <h3 className="l3">Session #2191</h3>
                        <div className="mb-05">
                            <FieldTimeOutlined /> 3 minute session on Oct 19
                        </div>
                        <div className="mb-05">
                            <PushpinOutlined /> Paris, FR
                        </div>
                        <div>
                            <UserOutlined style={{ marginRight: 4 }} />
                            <Link to="" target="_blank" style={{ display: 'inline-flex', alignItems: 'center' }}>
                                <span style={{ marginRight: 4 }}>marius@posthog.com</span>
                                <IconExternalLink />
                            </Link>
                        </div>
                        <div className="mt">
                            <div>
                                <b>Tags</b>
                            </div>
                            {tags.map((tag, index) => {
                                return (
                                    <Tag
                                        key={index}
                                        color={colorForString(tag)}
                                        closable
                                        onClose={() => removeTag(tag)}
                                        className="tag-wrapper"
                                    >
                                        {tag}
                                    </Tag>
                                )
                            })}
                            <span className="tag-wrapper" style={{ display: 'inline-flex' }}>
                                <Tag
                                    onClick={toggleAddingTagShown}
                                    data-attr="button-add-tag"
                                    style={{
                                        cursor: 'pointer',
                                        borderStyle: 'dashed',
                                        backgroundColor: '#ffffff',
                                        display: addingTagShown ? 'none' : 'initial',
                                    }}
                                >
                                    <PlusOutlined /> New Tag
                                </Tag>
                                <Input
                                    type="text"
                                    size="small"
                                    onBlur={toggleAddingTagShown}
                                    ref={addTagInput}
                                    style={{ width: 78, display: !addingTagShown ? 'none' : 'flex' }}
                                    value={addingTag}
                                    onChange={(e) => setAddingTag(e.target.value)}
                                    onPressEnter={createTag}
                                    disabled={tagsLoading}
                                    prefix={tagsLoading ? <SyncOutlined spin /> : null}
                                />
                            </span>
                        </div>
                    </Card>
                    <div className="mt" />
                    <Card className="card-elevated">
                        <h3 className="l3">Event timeline</h3>
                        <p className="text-muted text-small">
                            Click on an item to jump to that point in the recording.
                        </p>
                        <div className="timeline">
                            <div className="line" />
                            <div className="timeline-items">
                                <div>
                                    <Tag>https://posthog.com/blog/the-post-1</Tag>
                                </div>
                                <div className="current">
                                    <Tag>https://posthog.com/docs</Tag>
                                </div>
                                <div>
                                    <Tag>https://posthog.com/docs/integrations/message-formatting/#user</Tag>
                                </div>
                                <div>
                                    <Tag>https://posthog.com/blog/the-post-1</Tag>
                                </div>
                                <div>
                                    <Tag>https://posthog.com/docs</Tag>
                                </div>
                                <div>
                                    <Tag>https://posthog.com/docs/integrations/message-formatting/#user</Tag>
                                </div>
                            </div>
                        </div>
                    </Card>
                </Col>
            </Row>
        </div>
    )
}
