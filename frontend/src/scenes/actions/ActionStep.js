import React, { Component } from 'react'
import { EventName } from './EventName'
import { AppEditorLink } from 'lib/components/AppEditorLink/AppEditorLink'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import PropTypes from 'prop-types'
import { URL_MATCHING_HINTS } from 'scenes/actions/hints'
import { Card, Checkbox, Col, Input, Radio } from 'antd'
import { ExportOutlined } from '@ant-design/icons'

let getSafeText = (el) => {
    if (!el.childNodes || !el.childNodes.length) {
        return
    }
    let elText = ''
    el.childNodes.forEach((child) => {
        if (child.nodeType !== 3 || !child.textContent) {
            return
        }
        elText += child.textContent
            .trim()
            .replace(/[\r\n]/g, ' ')
            .replace(/[ ]+/g, ' ') // normalize whitespace
            .substring(0, 255)
    })
    return elText
}

export class ActionStep extends Component {
    constructor(props) {
        super(props)
        this.state = {
            step: props.step,
            selection: Object.keys(props.step).filter((key) => key !== 'id' && key !== 'isNew' && props.step[key]),
            inspecting: false,
        }
        this.AutocaptureFields = this.AutocaptureFields.bind(this)

        this.box = document.createElement('div')
        document.body.appendChild(this.box)
    }
    drawBox(element) {
        let rect = element.getBoundingClientRect()
        this.box.style.display = 'block'
        this.box.style.position = 'absolute'
        this.box.style.top = `${rect.top + window.pageYOffset}px`
        this.box.style.left = `${rect.left + window.pageXOffset}px`
        this.box.style.width = `${rect.right - rect.left}px`
        this.box.style.height = `${rect.bottom - rect.top}px`
        this.box.style.background = '#007bff'
        this.box.style.opacity = '0.5'
        this.box.style.zIndex = '9999999999'
    }
    onMouseOver = (event) => {
        let el = event.currentTarget
        this.drawBox(el)
        let query = this.props.simmer(el)
        // Turn tags into lower cases
        query = query.replace(/(^[A-Z]+| [A-Z]+)/g, (d) => d.toLowerCase())
        let tagName = el.tagName.toLowerCase()

        let selection = ['selector']
        if (tagName === 'a') {
            selection = ['href', 'selector']
        } else if (tagName === 'button') {
            selection = ['text', 'selector']
        } else if (el.getAttribute('name')) {
            selection = ['name', 'selector']
        }
        let step = {
            ...this.props.step,
            event: '$autocapture',
            tag_name: tagName,
            href: el.getAttribute('href') || '',
            name: el.getAttribute('name') || '',
            text: getSafeText(el) || '',
            selector: query || '',
            url: window.location.protocol + '//' + window.location.host + window.location.pathname,
        }
        this.setState(
            {
                element: el,
                selection,
            },
            () => this.sendStep(step)
        )
    }
    onKeyDown = (event) => {
        // stop selecting if esc key was pressed
        if (event.keyCode === 27) {
            this.stop()
        }
    }
    start() {
        this.setState({ inspecting: true })
        document.querySelectorAll('a, button, input, select, textarea, label').forEach((element) => {
            element.addEventListener('mouseover', this.onMouseOver, {
                capture: true,
            })
        })
        document.addEventListener('keydown', this.onKeyDown)
        document.body.style.transition = '0.7s box-shadow'
        // document.body.style.boxShadow = 'inset 0 0px 13px -2px #dc3545';
        document.body.style.boxShadow = 'inset 0 0px 30px -5px #007bff'
        this.box.addEventListener('click', this.stop)
    }
    stop = () => {
        this.setState({ inspecting: false })
        this.box.style.display = 'none'
        document.body.style.boxShadow = 'none'
        document.querySelectorAll('a, button, input, select, textarea, label').forEach((element) => {
            element.removeEventListener('mouseover', this.onMouseOver, {
                capture: true,
            })
        })
        document.removeEventListener('keydown', this.onKeyDown)
    }
    sendStep = (step) => {
        step.selection = this.state.selection
        this.props.onChange(step)
    }
    Option = (props) => {
        let onChange = (e) => {
            this.props.step[props.item] = e.target.value

            if (e.target.value && this.state.selection.indexOf(props.item) === -1) {
                this.setState({ selection: this.state.selection.concat([props.item]) }, () =>
                    this.sendStep(this.props.step)
                )
            } else if (!e.target.value && this.state.selection.indexOf(props.item) > -1) {
                this.setState(
                    {
                        selection: this.state.selection.filter((i) => i !== props.item),
                    },
                    () => this.sendStep(this.props.step)
                )
            } else {
                this.sendStep(this.props.step)
            }
        }

        return (
            <div className={'mb ' + (this.state.selection.indexOf(props.item) > -1 && 'selected')}>
                <label>
                    <Checkbox
                        checked={this.state.selection.indexOf(props.item) > -1}
                        value={props.item}
                        onChange={(e) => {
                            let { selection } = this.state
                            if (e.target.checked) {
                                selection.push(props.item)
                            } else {
                                selection = selection.filter((i) => i !== props.item)
                            }
                            this.setState({ selection }, () => this.sendStep(this.props.step))
                        }}
                    />{' '}
                    {props.label} {props.extra_options}
                </label>
                {props.item === 'selector' ? (
                    <Input.TextArea onChange={onChange} value={this.props.step[props.item] || ''} />
                ) : (
                    <Input
                        data-attr="edit-action-url-input"
                        onChange={onChange}
                        value={this.props.step[props.item] || ''}
                    />
                )}
            </div>
        )
    }
    TypeSwitcher = () => {
        let { step } = this.props
        const handleChange = (e) => {
            const type = e.target.value
            if (type === '$autocapture') {
                this.setState(
                    {
                        selection: Object.keys(step).filter((key) => key !== 'id' && key !== 'isNew' && step[key]),
                    },
                    () => this.sendStep({ ...step, event: '$autocapture' })
                )
            } else if (type === 'event') {
                this.setState({ selection: [] }, () => this.sendStep({ ...step, event: '' }))
            } else if (type === '$pageview') {
                this.setState({ selection: ['url'] }, () =>
                    this.sendStep({
                        ...step,
                        event: '$pageview',
                        url: step.url,
                    })
                )
            }
        }

        return (
            <div className={`type-switcher${step.event === undefined ? ' unselected' : ''}`}>
                <Radio.Group
                    buttonStyle="solid"
                    onChange={handleChange}
                    value={
                        step.event === '$autocapture' || step.event === '$pageview' || step.event === undefined
                            ? step.event
                            : 'event'
                    }
                >
                    <Radio.Button value="$autocapture">Autocapture</Radio.Button>
                    <Radio.Button value="event">Custom event</Radio.Button>
                    <Radio.Button value="$pageview">Page view</Radio.Button>
                </Radio.Group>
            </div>
        )
    }
    AutocaptureFields({ step, actionId }) {
        const AndC = () => {
            return (
                <div className="text-center">
                    <span className="stateful-badge and">AND</span>
                </div>
            )
        }
        return (
            <div>
                <span>
                    <AppEditorLink actionId={actionId} style={{ margin: '1rem 0' }}>
                        Select element on site <ExportOutlined />
                    </AppEditorLink>
                    <a
                        href="https://posthog.com/docs/features/actions"
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ marginLeft: 8 }}
                    >
                        See documentation.
                    </a>{' '}
                </span>
                <this.Option
                    item="href"
                    label="Link href equals"
                    selector={this.state.element && 'a[href="' + this.state.element.getAttribute('href') + '"]'}
                />
                <AndC />
                <this.Option item="text" label="Text equals" />
                <AndC />
                <this.Option item="selector" label="HTML selector matches" selector={step.selector} />
                <div style={{ marginBottom: 18 }}>
                    <AndC />
                </div>
                <this.Option item="url" extra_options={<this.URLMatching step={step} />} label="URL" />
                {step?.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                    <small style={{ display: 'block', marginTop: -12 }}>{URL_MATCHING_HINTS[step.url_matching]}</small>
                )}
            </div>
        )
    }
    URLMatching = ({ step }) => {
        const handleURLMatchChange = (e) => {
            this.sendStep({ ...step, url_matching: e.target.value })
        }
        return (
            <Radio.Group
                buttonStyle="solid"
                onChange={handleURLMatchChange}
                value={step.url_matching || 'contains'}
                size="small"
                style={{ paddingBottom: 16 }}
            >
                <Radio.Button value="contains">contains</Radio.Button>
                <Radio.Button value="regex">matches regex</Radio.Button>
                <Radio.Button value="exact">matches exactly</Radio.Button>
            </Radio.Group>
        )
    }
    render() {
        let { step, actionId, isOnlyStep, index, identifier, onDelete } = this.props

        return (
            <Col span={24} md={12}>
                <Card className="action-step" style={{ overflow: 'visible' }}>
                    {index > 0 && <div className="stateful-badge mc-main or">OR</div>}
                    <div>
                        {!isOnlyStep && (
                            <div className="remove-wrapper">
                                <button type="button" aria-label="delete" onClick={onDelete}>
                                    <span aria-hidden="true">&times;</span>
                                </button>
                            </div>
                        )}
                        <div className="mb">
                            <b>Match Group #{this.props.index + 1}</b>
                        </div>
                        {<this.TypeSwitcher />}
                        <div
                            style={{
                                marginTop: step.event === '$pageview' ? 20 : 8,
                                paddingBottom: 0,
                            }}
                        >
                            {step.event === '$autocapture' && (
                                <this.AutocaptureFields step={step} actionId={actionId} />
                            )}
                            {step.event != null && step.event !== '$autocapture' && step.event !== '$pageview' && (
                                <div style={{ marginTop: '2rem' }}>
                                    <label>Event name: {step.event}</label>
                                    <EventName
                                        value={step.event}
                                        isActionStep={true}
                                        onChange={(value) =>
                                            this.sendStep({
                                                ...step,
                                                event: value,
                                            })
                                        }
                                    />
                                </div>
                            )}
                            {step.event === '$pageview' && (
                                <div>
                                    <this.Option
                                        item="url"
                                        extra_options={<this.URLMatching step={step} />}
                                        label="URL"
                                    />
                                    {step.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                                        <small style={{ display: 'block', marginTop: -12 }}>
                                            {URL_MATCHING_HINTS[step.url_matching]}
                                        </small>
                                    )}
                                </div>
                            )}

                            {step.event && (
                                <div className="property-filters">
                                    <h3 className="l3">Filters</h3>
                                    {(!step.properties || step.properties.length === 0) && (
                                        <div className="text-muted">This match group has no additional filters.</div>
                                    )}
                                    <PropertyFilters
                                        propertyFilters={step.properties}
                                        pageKey={identifier}
                                        onChange={(properties) => {
                                            this.sendStep({
                                                ...this.props.step, // Not sure why, but the normal 'step' variable does not work here
                                                properties,
                                            })
                                        }}
                                        showConditionBadges
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </Card>
            </Col>
        )
    }
}
ActionStep.propTypes = {
    step: PropTypes.object,
    simmer: PropTypes.func,
    index: PropTypes.number.isRequired,
}
