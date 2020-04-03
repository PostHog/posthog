import React, {Component} from 'react'

export default class ActionSelectTab extends Component {
    render(){
        let {entityType, chooseEntityType} = this.props
        return (
            <div style={{display: 'flex', flexDirection: 'row', height: '25px', borderBottom: "1px solid #cccccc"}}>
                <div style={{backgroundColor: entityType == 0 ? 'white' : '#eeeeee', flex: 1, display:'flex', justifyContent: 'center', borderTopLeftRadius: '5px'}} onClick={() => chooseEntityType(0)}>Action</div>
                <div style={{backgroundColor: entityType == 1 ? 'white' : '#eeeeee', flex: 1, display:'flex', justifyContent: 'center', borderTopRightRadius: '5px'}} onClick={() => chooseEntityType(1)}>Event</div>
            </div>
        )
    }
}