import React, {Component} from 'react'

export default class ActionSelectTab extends Component {
    render(){
        let {entityType, chooseEntityType, allTypes} = this.props
        return (
            <div style={{display: 'flex', flexDirection: 'row', height: '25px', borderBottom: "1px solid #cccccc"}}>
                {
                    allTypes.map((type, index) => <div key={index} style={{backgroundColor: entityType == type ? 'white' : '#eeeeee', flex: 1, display:'flex', justifyContent: 'center', borderTopLeftRadius: '5px'}} onClick={() => chooseEntityType(type)}>{type}</div>)
                }
            </div>
        )
    }
}