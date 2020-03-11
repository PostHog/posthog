import React, { Component } from 'react'
import { Card } from '../../lib/utils'

export default class ActionSelectInfo extends Component {
  infoDiv = React.createRef()
  componentDidMount(prevProps) {
    if(!this.infoDiv.current) return;
    let rect = this.props.boundingRect;
    this.infoDiv.current.style.top = (rect.top - rect.height/2) + 'px';
    this.infoDiv.current.style.left = rect.left + rect.width + 'px';
    this.infoDiv.current.style.opacity = 1;
  }
  componentDidUpdate() {
    this.componentDidMount();
  }
  render() {
    let { action, isOpen } = this.props;
    if(!action) return null;
    return <div className='select-box-info' ref={this.infoDiv} style={{opacity: isOpen ? 1 : 0}}>
      <div style={{marginBottom: '0.5rem'}}>{action.name}</div>
      {action.steps.map((step, index) => <div>
        <Card key={step.id} style={{marginBottom: 0}}>
          <div className='card-body'>
            <strong>{step.event[0] == '$' ? step.event[1].toUpperCase() + step.event.slice(2) : step.event}</strong>
            <ul style={{listStyle: 'none'}}>
              {step.selector && <li>
                CSS selector matches
                <pre>{step.selector}</pre>
              </li>}
              {step.tag_name && <li>Tag name matches <pre>{step.tag_name}</pre></li>}
              {step.text && <li>Text matches <pre>{step.text}</pre></li>}
              {step.href && <li>Link HREF matches <pre>{step.href}</pre></li>}
              {step.url && <li>URL {step.url_matching == 'contains' ? 'contains' : 'matches'} <pre>{step.url}</pre></li>}
            </ul>
          </div>
        </Card>
        {index < action.steps.length -1 && <div className='secondary' style={{textAlign: 'center', margin: '1rem'}}>OR</div>}
      </div>)}
    </div>
  }
}
