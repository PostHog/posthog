import{b as S,e as E,g as R,j as N}from"/static/chunk-SJXEOBQC.js";var D=S((_,n)=>{E();N();R();function a(O){let e={className:"number",begin:"[1-9][0-9]*",relevance:0},T={className:"symbol",begin:":[^\\]]+"},s={className:"built_in",begin:"(AR|P|PAYLOAD|PR|R|SR|RSR|LBL|VR|UALM|MESSAGE|UTOOL|UFRAME|TIMER|TIMER_OVERFLOW|JOINT_MAX_SPEED|RESUME_PROG|DIAG_REC)\\[",end:"\\]",contains:["self",e,T]},A={className:"built_in",begin:"(AI|AO|DI|DO|F|RI|RO|UI|UO|GI|GO|SI|SO)\\[",end:"\\]",contains:["self",e,O.QUOTE_STRING_MODE,T]};return{name:"TP",keywords:{keyword:"ABORT ACC ADJUST AND AP_LD BREAK CALL CNT COL CONDITION CONFIG DA DB DIV DETECT ELSE END ENDFOR ERR_NUM ERROR_PROG FINE FOR GP GUARD INC IF JMP LINEAR_MAX_SPEED LOCK MOD MONITOR OFFSET Offset OR OVERRIDE PAUSE PREG PTH RT_LD RUN SELECT SKIP Skip TA TB TO TOOL_OFFSET Tool_Offset UF UT UFRAME_NUM UTOOL_NUM UNLOCK WAIT X Y Z W P R STRLEN SUBSTR FINDSTR VOFFSET PROG ATTR MN POS",literal:"ON OFF max_speed LPOS JPOS ENABLE DISABLE START STOP RESET"},contains:[s,A,{className:"keyword",begin:"/(PROG|ATTR|MN|POS|END)\\b"},{className:"keyword",begin:"(CALL|RUN|POINT_LOGIC|LBL)\\b"},{className:"keyword",begin:"\\b(ACC|CNT|Skip|Offset|PSPD|RT_LD|AP_LD|Tool_Offset)"},{className:"number",begin:"\\d+(sec|msec|mm/sec|cm/min|inch/min|deg/sec|mm|in|cm)?\\b",relevance:0},O.COMMENT("//","[;$]"),O.COMMENT("!","[;$]"),O.COMMENT("--eg:","$"),O.QUOTE_STRING_MODE,{className:"string",begin:"'",end:"'"},O.C_NUMBER_MODE,{className:"variable",begin:"\\$[A-Za-z0-9_]+"}]}}n.exports=a});export default D();
//# sourceMappingURL=/static/tp-Z5XOVXTA.js.map
