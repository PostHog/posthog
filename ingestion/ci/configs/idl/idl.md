# IDL - Interface Definition Language

This directory is responsible for defining the schemas of the data between services.
Primarily this will be between services and ClickHouse, but can be really any thing at the boundry of services.

The reason why we do this is because it makes generating code, validating data, and understanding the system a whole lot easier. We've had a few customers request this of us for engineering a deeper integration with us.
