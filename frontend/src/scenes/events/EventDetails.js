import React, { Component } from 'react'

export class EventDetails extends Component {
    constructor(props) {
        super(props)
        this.state = { selected: 'properties' }
        this.ShowElements = this.ShowElements.bind(this)
    }
    indent(n) {
        return Array(n)
            .fill()
            .map(() => <span>&nbsp;&nbsp;&nbsp;&nbsp;</span>)
    }
    ShowElements(props) {
        let { elements } = props
        return (
            <div>
                {elements.map((element, index) => (
                    <pre
                        className="code"
                        style={{
                            margin: 0,
                            padding: 0,
                            borderRadius: 0,
                            ...(index == elements.length - 1
                                ? { backgroundColor: 'var(--blue)' }
                                : {}),
                        }}
                    >
                        {this.indent(index)}
                        &lt;{element.tag_name}
                        {element.attr_id && ' id="' + element.attr_id + '"'}
                        {Object.entries(element.attributes).map(
                            ([key, value]) => (
                                <span>
                                    {' '}
                                    {key.replace('attr__', '')}="{value}"
                                </span>
                            )
                        )}
                        &gt;{element.text}
                        {index == elements.length - 1 && (
                            <span>&lt;/{element.tag_name}&gt;</span>
                        )}
                    </pre>
                ))}
                {[...elements]
                    .reverse()
                    .slice(1)
                    .map((element, index) => (
                        <pre
                            className="code"
                            style={{ margin: 0, padding: 0, borderRadius: 0 }}
                        >
                            {this.indent(elements.length - index - 2)}
                            &lt;/{element.tag_name}&gt;
                        </pre>
                    ))}
            </div>
        )
    }
    render() {
        let { event } = this.props
        let elements = [...event.elements].reverse()
        return (
            <div className="row">
                <div className="col-2">
                    <div
                        className="nav flex-column nav-pills"
                        id="v-pills-tab"
                        role="tablist"
                        aria-orientation="vertical"
                    >
                        <a
                            className={
                                'cursor-pointer nav-link ' +
                                (this.state.selected == 'properties' &&
                                    'active')
                            }
                            onClick={() =>
                                this.setState({ selected: 'properties' })
                            }
                        >
                            Properties
                        </a>
                        {elements.length > 0 && (
                            <a
                                className={
                                    'cursor-pointer nav-link ' +
                                    (this.state.selected == 'elements' &&
                                        'active')
                                }
                                onClick={() =>
                                    this.setState({ selected: 'elements' })
                                }
                            >
                                Elements
                            </a>
                        )}
                    </div>
                </div>
                <div className="col-10">
                    {this.state.selected == 'properties' ? (
                        <div className="d-flex flex-wrap flex-column">
                            {Object.keys(event.properties)
                                .sort()
                                .map(key => (
                                    <div style={{ flex: '0 1 ' }} key={key}>
                                        <strong>{key}:</strong>
                                        {this.props.event.properties[key]}
                                    </div>
                                ))}
                        </div>
                    ) : (
                        <this.ShowElements elements={elements} />
                    )}
                </div>
            </div>
        )
    }
}
