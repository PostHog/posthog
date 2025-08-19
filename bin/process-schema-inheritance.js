#!/usr/bin/env node

/**
 * Post-processes the generated schema.json to preserve TypeScript inheritance
 * by converting flat definitions to allOf patterns where appropriate.
 */

const fs = require('fs');
const path = require('path');

// Read the TypeScript source to extract inheritance relationships
function parseInheritanceFromTypeScript() {
    const schemaGeneralPath = path.join(__dirname, '../frontend/src/queries/schema/schema-general.ts');
    const content = fs.readFileSync(schemaGeneralPath, 'utf8');
    
    const inheritanceMap = new Map();
    const lines = content.split('\n');
    
    for (const line of lines) {
        // Match interface inheritance: "interface Child extends Parent" or "interface Child extends Parent<Type>"
        const match = line.match(/^export\s+interface\s+(\w+).*extends\s+([^<\s,]+)/);
        if (match) {
            const [, child, parent] = match;
            inheritanceMap.set(child, parent);
        }
    }
    
    return inheritanceMap;
}

// Transform schema definitions to use allOf for inheritance
function transformSchema(schema, inheritanceMap) {
    const definitions = schema.definitions || {};
    
    for (const [childName, parentName] of inheritanceMap.entries()) {
        const childDef = definitions[childName];
        const parentDef = definitions[parentName];
        
        if (childDef && parentDef) {
            // Only process if both definitions exist and child has object structure
            if (childDef.type === 'object' || childDef.properties) {
                // Create allOf structure preserving child-specific properties
                const childProps = childDef.properties || {};
                const parentProps = parentDef.properties || {};
                const childOnlyProps = { ...childProps };
                
                // Remove parent properties from child
                for (const prop of Object.keys(parentProps)) {
                    delete childOnlyProps[prop];
                }
                
                // Only create allOf if there are meaningful differences
                if (Object.keys(childOnlyProps).length > 0 || (childDef.required && childDef.required.length > 0)) {
                    // Transform to allOf pattern
                    const childPart = {
                        type: 'object',
                        additionalProperties: false
                    };
                    
                    if (Object.keys(childOnlyProps).length > 0) {
                        childPart.properties = childOnlyProps;
                    }
                    
                    const parentRequired = parentDef.required || [];
                    const childRequired = childDef.required?.filter(req => !parentRequired.includes(req)) || [];
                    if (childRequired.length > 0) {
                        childPart.required = childRequired;
                    }
                    
                    definitions[childName] = {
                        allOf: [
                            { $ref: `#/definitions/${parentName}` },
                            childPart
                        ]
                    };
                    
                    console.log(`  Transformed ${childName} -> ${parentName} inheritance`);
                }
            }
            
            // Add discriminator support for key parent classes
            if (!parentDef.discriminator && ['Node', 'DataNode', 'EntityNode'].includes(parentName)) {
                definitions[parentName] = {
                    ...parentDef,
                    discriminator: {
                        propertyName: 'kind'
                    }
                };
            }
        }
    }
    
    return schema;
}

function main() {
    const schemaPath = path.join(__dirname, '../frontend/src/queries/schema.json');
    
    try {
        // Parse inheritance relationships from TypeScript
        const inheritanceMap = parseInheritanceFromTypeScript();
        console.log(`Found ${inheritanceMap.size} inheritance relationships`);
        
        // Load and transform schema
        const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));
        const transformedSchema = transformSchema(schema, inheritanceMap);
        
        // Write back transformed schema
        fs.writeFileSync(schemaPath, JSON.stringify(transformedSchema, null, 2));
        console.log('Schema inheritance processing completed');
        
    } catch (error) {
        console.error('Error processing schema inheritance:', error);
        process.exit(1);
    }
}

if (require.main === module) {
    main();
}