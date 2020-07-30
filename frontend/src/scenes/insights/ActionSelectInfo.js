import React, { Component } from 'react'
import { Card } from '../../lib/utils'

export class ActionSelectInfo extends Component {
    infoDiv = React.createRef()
    componentDidMount() {
        if (!this.infoDiv.current) return
        let rect = this.props.boundingRect
        this.infoDiv.current.style.top = rect.top - rect.height / 2 + 'px'
        this.infoDiv.current.style.left = rect.left + rect.width + 'px'
        this.infoDiv.current.style.opacity = 1
    }
    componentDidUpdate() {
        this.componentDidMount()
    }
    render() {
        let { entity, isOpen } = this.props
        if (!entity) return null
        return (
            <div className="select-box-info" ref={this.infoDiv} style={{ opacity: isOpen ? 1 : 0 }}>
                <div style={{ marginBottom: '0.5rem' }}>{entity.name}</div>
                {entity.steps &&
                    entity.steps.map((step, index) => (
                        <div key={step.id}>
                            <Card key={step.id} style={{ marginBottom: 0 }}>
                                <div className="card-body">
                                    <strong>
                                        {step.event && step.event[0] == '$'
                                            ? step.event[1].toUpperCase() + step.event.slice(2)
                                            : step.event}
                                    </strong>
                                    <ul style={{ listStyle: 'none' }}>
                                        {step.selector && (
                                            <li>
                                                CSS selector matches
                                                <pre>{step.selector}</pre>
                                            </li>
                                        )}
                                        {step.tag_name && (
                                            <li>
                                                Tag name matches <pre>{step.tag_name}</pre>
                                            </li>
                                        )}
                                        {step.text && (
                                            <li>
                                                Text matches <pre>{step.text}</pre>
                                            </li>
                                        )}
                                        {step.href && (
                                            <li>
                                                Link HREF matches <pre>{step.href}</pre>
                                            </li>
                                        )}
                                        {step.url && (
                                            <li>
                                                URL{' '}
                                                {step.url_matching === 'regex'
                                                    ? 'matches regex'
                                                    : step.url_matching === 'exact'
                                                    ? 'matches exactly'
                                                    : 'contains'}{' '}
                                                <pre>{step.url}</pre>
                                            </li>
                                        )}
                                    </ul>
                                </div>
                            </Card>
                            {index < entity.steps.length - 1 && (
                                <div className="secondary" style={{ textAlign: 'center', margin: '1rem' }}>
                                    OR
                                </div>
                            )}
                        </div>
                    ))}
            </div>
        )
    }
}
